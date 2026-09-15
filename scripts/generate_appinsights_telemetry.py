"""Send controlled synthetic checkout telemetry to Azure Application Insights.

This script is intentionally isolated from the application and MCP workflow.
It emits a short normal period followed by degraded checkout activity.
"""

import argparse
import logging
import os
import time

from dotenv import load_dotenv
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry._logs import get_logger_provider

SERVICE_NAME = "checkout-service"
INCIDENT_ID = "1042"
SYNTHETIC_MARKER = True
LOGGER_NAME = "evalagent.synthetic.checkout"


class _TelemetryFields(logging.Filter):
    """Attach stable fields to records collected by the OpenTelemetry logger."""

    def filter(self, record):
        record.service_name = SERVICE_NAME
        record.incident_id = INCIDENT_ID
        record.synthetic_telemetry = SYNTHETIC_MARKER
        return True


def _configure_telemetry():
    load_dotenv()
    if not os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        raise RuntimeError(
            "APPLICATIONINSIGHTS_CONNECTION_STRING is not configured."
        )

    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": "synthetic-development",
            "deployment.environment": "synthetic-development",
        }
    )
    configure_azure_monitor(
        resource=resource,
        logger_name=LOGGER_NAME,
        disable_offline_storage=True,
    )

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.addFilter(_TelemetryFields())
    return trace.get_tracer("evalagent.synthetic.checkout"), logger


def _attributes(**values):
    return {
        "service.name": SERVICE_NAME,
        "incident_id": INCIDENT_ID,
        "telemetry.synthetic": SYNTHETIC_MARKER,
        **values,
    }


def _redis_dependency(tracer, logger, *, degraded):
    with tracer.start_as_current_span(
        "redis GET checkout:cart",
        kind=SpanKind.CLIENT,
        attributes=_attributes(
            **{
                "db.system": "redis",
                "db.operation.name": "GET",
                "server.address": "checkout-redis",
                "peer.service": "redis",
            }
        ),
    ) as span:
        if degraded:
            error = TimeoutError("synthetic Redis connection pool timeout")
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, "Redis timeout"))
            logger.error(
                "Synthetic Redis timeout during checkout",
                extra={
                    "dependency_name": "redis",
                    "failure_mode": "connection_pool_timeout",
                },
            )
            raise error

        logger.info(
            "Synthetic Redis cart lookup completed",
            extra={"dependency_name": "redis"},
        )


def _checkout_request(tracer, logger, request_number, *, degraded):
    status_code = 503 if degraded else 200
    duration_ms = 850 if degraded else 45
    with tracer.start_as_current_span(
        "POST /checkout",
        kind=SpanKind.SERVER,
        attributes=_attributes(
            **{
                "http.request.method": "POST",
                "url.path": "/checkout",
                "http.response.status_code": status_code,
                "http.route": "/checkout",
                "checkout.request_number": request_number,
                "checkout.phase": "degraded" if degraded else "normal",
                "synthetic.duration_ms": duration_ms,
            }
        ),
    ) as span:
        logger.info(
            "Synthetic checkout request started",
            extra={
                "request_number": request_number,
                "checkout_phase": "degraded" if degraded else "normal",
            },
        )
        try:
            _redis_dependency(tracer, logger, degraded=degraded)
        except TimeoutError:
            span.record_exception(
                TimeoutError("synthetic checkout failed after Redis timeout")
            )
            span.set_status(Status(StatusCode.ERROR, "Checkout dependency failure"))
            logger.error(
                "Synthetic checkout request failed",
                extra={"http_status_code": status_code},
            )
            return

        logger.info(
            "Synthetic checkout request completed",
            extra={"http_status_code": status_code},
        )


def _flush_telemetry():
    trace_provider = trace.get_tracer_provider()
    if hasattr(trace_provider, "force_flush"):
        trace_provider.force_flush()

    logger_provider = get_logger_provider()
    if hasattr(logger_provider, "force_flush"):
        logger_provider.force_flush()


def main():
    parser = argparse.ArgumentParser(
        description="Send synthetic checkout telemetry to Application Insights."
    )
    parser.add_argument(
        "--normal-count",
        type=int,
        default=5,
        help="Number of normal checkout requests to emit.",
    )
    parser.add_argument(
        "--degraded-count",
        type=int,
        default=5,
        help="Number of degraded checkout requests to emit.",
    )
    args = parser.parse_args()

    if args.normal_count < 0 or args.degraded_count < 0:
        parser.error("request counts must be zero or greater")
    if args.normal_count == 0 and args.degraded_count == 0:
        parser.error("at least one request must be generated")

    tracer, logger = _configure_telemetry()

    for request_number in range(1, args.normal_count + 1):
        _checkout_request(
            tracer,
            logger,
            request_number,
            degraded=False,
        )

    logger.warning(
        "Synthetic checkout incident degradation begins",
        extra={"failure_mode": "redis_connection_pool_saturation"},
    )

    for offset in range(args.degraded_count):
        _checkout_request(
            tracer,
            logger,
            args.normal_count + offset + 1,
            degraded=True,
        )

    _flush_telemetry()
    time.sleep(2)
    print(
        "Synthetic checkout telemetry submitted: "
        f"normal={args.normal_count}, degraded={args.degraded_count}, "
        f"incident_id={INCIDENT_ID}"
    )


if __name__ == "__main__":
    main()
