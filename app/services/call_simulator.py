from __future__ import annotations

from ..schemas.test_flow import (
    CallSimulationResult,
    LocalBusinessStatus,
    LocalCallScenario,
    LocalCallResult,
    LocalCallStatus,
)


class CallSimulatorService:
    def simulate(self, scenario: LocalCallScenario) -> CallSimulationResult:
        if scenario == LocalCallScenario.CONFIRMED:
            return CallSimulationResult(
                call_status=LocalCallStatus.ANSWERED,
                call_result=LocalCallResult.CONFIRMED,
                business_status=LocalBusinessStatus.CONFIRMED_BY_CALL,
                should_send_whatsapp=False,
            )

        if scenario == LocalCallScenario.FAILED:
            return CallSimulationResult(
                call_status=LocalCallStatus.FAILED,
                call_result=LocalCallResult.NOT_CONFIRMED,
                business_status=LocalBusinessStatus.FAILED_CALL,
                should_send_whatsapp=True,
            )

        if scenario == LocalCallScenario.INCONCLUSIVE:
            return CallSimulationResult(
                call_status=LocalCallStatus.ANSWERED,
                call_result=LocalCallResult.INCONCLUSIVE,
                business_status=LocalBusinessStatus.INCONCLUSIVE_CALL,
                should_send_whatsapp=True,
            )

        return CallSimulationResult(
            call_status=LocalCallStatus.NOT_ANSWERED,
            call_result=LocalCallResult.NOT_ANSWERED,
            business_status=LocalBusinessStatus.NOT_ANSWERED,
            should_send_whatsapp=True,
        )
