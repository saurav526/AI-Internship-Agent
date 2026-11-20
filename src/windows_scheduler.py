"""Windows Task Scheduler Manager for AI Internship Agent Daily Discovery.

Configures and verifies the Windows Scheduled Task:
- Task Name: "AI Internship Agent Daily Discovery"
- Schedule: Daily at 09:00 AM (Local Windows Timezone: Asia/Kolkata / India Standard Time)
- Working Directory: C:\\Users\\Asus\\Downloads\\AI-Internship-Agent
- MultipleInstancesPolicy: IgnoreNew (prevents overlapping / duplicate executions)
- StartWhenAvailable: true (runs missed scheduled execution as soon as the computer wakes or turns on)
- RestartOnFailure: 3 retries at 10-minute intervals for temporary failures
- Execution Logging: logs/daily_scheduler.log
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from src.logger import get_logger

logger = get_logger("windows_scheduler")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "AI Internship Agent Daily Discovery"
TASK_XML_PATH = PROJECT_ROOT / "data" / "daily_discovery_task.xml"
BATCH_RUNNER_PATH = PROJECT_ROOT / "run_daily_discovery.bat"


def resolve_project_python() -> str:
    """Return the verified Python executable for the project (.venv if populated, else active system Python)."""
    venv_py = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        try:
            res = subprocess.run(
                [str(venv_py), "-c", "import pydantic, sklearn, pymupdf, docx, dotenv"],
                capture_output=True,
                timeout=5,
            )
            if res.returncode == 0:
                return str(venv_py)
        except Exception:
            pass

    sys_py = Path("C:/Python314/python.exe")
    if sys_py.exists():
        return str(sys_py)
    return sys.executable


def generate_task_scheduler_xml() -> Path:
    """Generate a Windows Task Scheduler 1.2 XML definition with StartWhenAvailable, IgnoreNew, and RestartOnFailure."""
    TASK_XML_PATH.parent.mkdir(parents=True, exist_ok=True)
    start_boundary = datetime.now().strftime("%Y-%m-%d") + "T09:00:00"

    xml_content = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}</Date>
    <Author>{os.getenv("USERNAME", "Asus")}</Author>
    <Description>Daily 09:00 AM IST AI Internship Discovery, Resume Matching, Draft Preparation, Report Generation and Summary Email Notification.</Description>
    <URI>\\{TASK_NAME}</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start_boundary}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT10M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{BATCH_RUNNER_PATH}</Command>
      <WorkingDirectory>{PROJECT_ROOT}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""
    TASK_XML_PATH.write_bytes(xml_content.encode("utf-16"))
    return TASK_XML_PATH


def register_windows_scheduled_task(run_immediately: bool = False) -> Dict[str, Any]:
    """Register the 'AI Internship Agent Daily Discovery' task in Windows Task Scheduler and optionally trigger an immediate test run."""
    xml_path = generate_task_scheduler_xml()
    python_exe = resolve_project_python()

    create_cmd = [
        "schtasks",
        "/Create",
        "/TN",
        TASK_NAME,
        "/XML",
        str(xml_path),
        "/F",
    ]
    result_info: Dict[str, Any] = {
        "task_name": TASK_NAME,
        "schedule": "Daily at 09:00 AM IST (Asia/Kolkata)",
        "xml_path": str(xml_path),
        "batch_runner": str(BATCH_RUNNER_PATH),
        "python_executable": python_exe,
        "working_directory": str(PROJECT_ROOT),
        "start_when_available": True,
        "multiple_instances_policy": "IgnoreNew",
        "restart_on_failure": "3 retries every 10 minutes",
        "registered": False,
        "triggered_immediate_run": False,
        "query_output": "",
    }

    try:
        proc = subprocess.run(create_cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            result_info["registered"] = True
            logger.info("Registered Windows Scheduled Task '%s' successfully.", TASK_NAME)
        else:
            result_info["error"] = (proc.stderr or proc.stdout).strip()
            logger.warning("schtasks /Create returned non-zero (%s): %s", proc.returncode, result_info["error"])
    except Exception as exc:
        result_info["error"] = str(exc)
        logger.warning("schtasks /Create exception: %s", exc)

    if result_info["registered"] and run_immediately:
        try:
            run_proc = subprocess.run(
                ["schtasks", "/Run", "/TN", TASK_NAME],
                capture_output=True,
                text=True,
                timeout=15,
            )
            result_info["triggered_immediate_run"] = run_proc.returncode == 0
        except Exception as exc:
            result_info["run_error"] = str(exc)

    if result_info["registered"]:
        try:
            q_proc = subprocess.run(
                ["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if q_proc.returncode == 0:
                result_info["query_output"] = q_proc.stdout.strip()
        except Exception:
            pass

    return result_info


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Register and verify Windows Task Scheduler daily discovery task")
    parser.add_argument("--register", action="store_true", help="Register the task in Windows Task Scheduler")
    parser.add_argument("--run-now", action="store_true", help="Trigger the scheduled task immediately after registering")
    args = parser.parse_args()

    generate_task_scheduler_xml()
    if args.register or args.run_now:
        res = register_windows_scheduled_task(run_immediately=args.run_now)
        print(json.dumps(res, indent=2))
    else:
        print(json.dumps({"xml_generated": str(TASK_XML_PATH), "python_exe": resolve_project_python()}, indent=2))
