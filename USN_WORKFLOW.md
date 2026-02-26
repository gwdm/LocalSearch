# Persistent USN Journal Workflow

This directory contains the implementation of a persistent USN journal change tracking system that solves two key problems:

1. **Journal wraparound** - USN journal has limited size and wraps, losing history
2. **Docker USN access** - Docker containers can't access NTFS USN journal

## Architecture

```
┌─────────────────────┐
│  Windows Host       │
│  (Native Python)    │
│                     │
│  ┌───────────────┐ │
│  │ USN Collector │ │  Reads NTFS USN journal
│  │  (Admin)      │ │  Runs: Daily + Startup
│  └───────┬───────┘ │
│          │         │
│          v         │
│  ┌───────────────┐ │
│  │ usn_changes   │ │  Permanent log of all
│  │    .txt       │ │  file changes
│  └───────┬───────┘ │
└──────────┼─────────┘
           │ (bind mount)
           v
┌─────────────────────┐
│  Docker Container   │
│                     │
│  ┌───────────────┐ │
│  │ Scanner       │ │  Reads usn_changes.txt
│  └───────┬───────┘ │
│          v         │
│  ┌───────────────┐ │
│  │ Pipeline      │ │  Processes files
│  └───────┬───────┘ │
│          v         │
│  ┌───────────────┐ │
│  │ Trim Log      │ │ Removes processed entries
│  └───────────────┘ │
└─────────────────────┘
```

## Components

### 1. USN Collector (`usn_collector.py`)
- Reads NTFS USN journal
- Appends changes to `data/usn_changes.txt`
- Updates USN state checkpoints
- Runs natively on Windows (requires Admin)

### 2. Permanent Change Log (`data/usn_changes.txt`)
- Format: `timestamp|action|path`
- Survives journal wraparound
- Trimmed after successful ingestion
- Bind-mounted into Docker

### 3. Modified Scanner
- Priority: Permanent log → Live USN → Full scan
- Reads from `usn_changes.txt` if available
- Falls back to live USN or full scan

### 4. Auto-Trim
- Pipeline trims log after processing
- Removes entries for successfully indexed files
- Keeps unprocessed entries for next run

## Setup

### 1. Register Scheduled Task (Run as Admin)
```powershell
.\register-usn-task.ps1
```

This creates a Windows scheduled task that runs:
- **Daily at 2 AM**
- **At system startup**

The task runs `extract-and-collect.ps1` which collects USN changes.

### 2. Manual Collection (if needed)
```powershell
# Run as Administrator
python -m localsearch.cli collect-usn
```

### 3. Docker Operations
Docker will automatically:
- Extract `extract-and-collect.ps1` to `data/` on startup
- Read from `data/usn_changes.txt` during ingestion
- Trim processed entries after successful ingestion

## Workflow

### Daily Operation
```
2:00 AM → Scheduled task runs
       → USN Collector reads journal
       → New changes appended to usn_changes.txt
       → USN state updated

Later → Docker ingestion runs
      → Scanner reads usn_changes.txt
      → Files processed
      → Processed entries trimmed from log
```

### System Startup
```
Boot → Scheduled task (AtStartup) runs
    → USN Collector captures changes since last boot
    → Changes appended to usn_changes.txt
```

## Benefits

✅ **No journal wraparound** - Changes persisted to permanent file

✅ **Fast incremental scans** - No need to check 650K files

✅ **Docker compatible** - Container reads pre-collected changes

✅ **Self-contained** - Script extracted from Docker image

✅ **Automatic** - Runs daily + at startup

✅ **Resilient** - Missed runs don't lose data (USN state tracks position)

## Files

| File | Purpose |
|------|---------|
| `usn_collector.py` | Core USN collection logic |
| `extract-and-collect.ps1` | Host-side runner script |
| `register-usn-task.ps1` | Task scheduler registration |
| `data/usn_changes.txt` | Permanent change log |
| `data/usn_state.json` | USN journal checkpoints |
| `docker-entrypoint.sh` | Extracts script on container start |

## Monitoring

### Check Task Status
```powershell
Get-ScheduledTask -TaskName "LocalSearch-USN-Collector"
Get-ScheduledTaskInfo -TaskName "LocalSearch-USN-Collector"
```

### Run Task Manually
```powershell
# As Administrator
Start-ScheduledTask -TaskName "LocalSearch-USN-Collector"
```

### View Change Log
```powershell
Get-Content data\usn_changes.txt -Tail 20
```

### View USN State
```powershell
Get-Content data\usn_state.json
```

## Troubleshooting

### "Cannot open volume \\.\D:"
- USN collector requires **Administrator privileges**
- Make sure script runs as SYSTEM (scheduled task) or Admin (manual)

### Log keeps growing
- Pipeline should auto-trim after each ingestion
- Manual trim: Delete `usn_changes.txt` and run initial scan

### Missing changes
- Check task last run time: `Get-ScheduledTaskInfo`
- Check USN state timestamps in `usn_state.json`
- Run collector manually to catch up

### Initial Setup
If this is first use:
1. Run full scan once to establish USN baseline: `python -m localsearch.cli ingest`
2. This creates initial USN state in `data/usn_state.json`
3. From then on, USN collector will track incrementally
