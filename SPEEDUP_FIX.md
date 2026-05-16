# Supervisor Performance Fixes

Analysis of why the supervisor dashboard is slow and unresponsive, with fixes ranked by impact.

## The Core Problem

Every 3 seconds, the frontend polls `/api/status`, which calls `get_current_metrics()` for every running service. Each call:
- Blocks 0.1s per process for `cpu_percent(interval=0.1)` (psutil)
- Blocks 0.1s per child process (same call)
- Walks entire project directory trees with `os.walk()` for disk usage

With 5 services averaging 2 children each, that's 5 * 3 * 0.1 = **1.5 seconds of blocking per poll**, all on the async event loop. The dashboard page load (`GET /`) does the same work again.

---

## Fix 1: Stop computing metrics live on `/api/status`

**File:** `supervisor/main.py:457-480`
**Impact:** Largest single fix

The `/api/status` endpoint calls `resource_monitor.get_current_metrics()` for every running service. This does live psutil + disk walks. Instead, it should return **cached metrics** from the most recent monitor loop collection.

**Change:** Replace the live `get_current_metrics()` call in `get_status()` with a read from the last stored `Metric` row, or a simple in-memory cache that the monitor loop populates.

```python
# Before (blocks for seconds)
metrics = resource_monitor.get_current_metrics(service.name) if running else None

# After (instant read from cache)
metrics = resource_monitor.get_cached_metrics(service.name) if running else None
```

Add to `ResourceMonitor`:
```python
def __init__(self):
    self._running = False
    self._task = None
    self._cache: dict[str, dict] = {}  # service_name -> metrics dict

async def _collect_metrics(self):
    # ... existing collection code ...
    # At end of each service's collection:
    self._cache[service.name] = {
        "cpu_percent": round(cpu_percent, 1),
        "memory_mb": round(memory_mb, 1),
        "disk_mb": round(disk_mb, 1),
    }

def get_cached_metrics(self, service_name: str) -> dict | None:
    return self._cache.get(service_name)
```

Same fix applies to `GET /` dashboard endpoint (`main.py:230-257`) which also calls `get_current_metrics()`.

---

## Fix 2: Slow down frontend polling from 3s to 10-15s

**File:** `supervisor/static/core.js:134-136`
**Impact:** High - reduces server load by 3-5x

The status poll interval is 3 seconds. For a service supervisor, 10-15 seconds is fine.

```javascript
// Before
statusInterval = setInterval(() => {
    if (typeof updateStatus === 'function') updateStatus();
}, 3000);

// After
}, 10000);  // or 15000
```

---

## Fix 3: Run `cpu_percent()` without blocking interval

**File:** `supervisor/monitor.py:78-129`
**Impact:** High - eliminates 0.1s * N blocking calls

`psutil.Process.cpu_percent(interval=0.1)` blocks the thread for 0.1 seconds to measure CPU delta. Instead, call with `interval=None` which returns the CPU usage since the last call (non-blocking). The first call returns 0, but subsequent calls in the monitor loop return meaningful values.

```python
# Before (blocks 0.1s per process)
cpu_percent = proc.cpu_percent(interval=0.1)

# After (non-blocking, uses delta from last call)
cpu_percent = proc.cpu_percent(interval=None)
```

The same fix applies to child process CPU collection and to `get_current_metrics()` (if it's kept at all after Fix 1).

---

## Fix 4: Cache disk usage, don't compute on every status request

**File:** `supervisor/monitor.py:110-115, 204-210`
**Impact:** High for large project directories

`get_directory_size()` uses `os.walk()` which can be very slow for large directories. It's called:
- Every monitor loop iteration (for every service)
- Every `/api/status` request (via `get_current_metrics`)
- Every dashboard page load

**Change:** Only compute disk usage in the monitor loop (every 5 minutes). Cache the result. Never compute it inline in API requests.

The `get_current_metrics()` method (lines 154-213) computes disk usage fresh every time. If Fix 1 is applied (use cached metrics), this is already solved.

If `get_current_metrics()` is kept for the `/metrics/current` endpoint, at minimum skip the disk walk and return the last known value from the database:

```python
# Get disk from last metric instead of walking
last_metric = (Metric.select(Metric.disk_mb)
    .where(Metric.service == service, Metric.disk_mb.is_null(False))
    .order_by(Metric.timestamp.desc())
    .first())
result["disk_mb"] = round(last_metric.disk_mb, 1) if last_metric else 0.0
```

---

## Fix 5: Run monitor collection in executor (off event loop)

**File:** `supervisor/monitor.py:67-76`
**Impact:** Medium - stops monitor from blocking API responses

`_collect_metrics()` runs synchronously on the async event loop. Even with `interval=None` for CPU, the disk walks and psutil calls add latency to all concurrent API requests.

```python
async def _monitor_loop(self):
    while self._running:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._collect_metrics_sync)
            await self._cleanup_old_data()
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")
        await asyncio.sleep(config.monitor_interval)
```

---

## Fix 6: Reduce service log polling from 1s to 3-5s

**File:** `supervisor/static/monitoring.js:29`
**Impact:** Medium - reduces DB query load when viewing logs

When the logs modal is open, it polls every 1 second. This is unnecessary for a supervisor tool.

```javascript
// Before
logsInterval = setInterval(refreshServiceLogs, 1000);

// After
logsInterval = setInterval(refreshServiceLogs, 3000);
```

---

## Fix 7: Reduce supervisor log polling from 1s to 5s

**File:** `supervisor/static/monitoring.js:118`
**Impact:** Medium - same reasoning

```javascript
// Before
supervisorLogsInterval = setInterval(loadSupervisorLogs, 1000);

// After
supervisorLogsInterval = setInterval(loadSupervisorLogs, 5000);
```

---

## Fix 8: Read supervisor logs with `tail` instead of reading entire file

**File:** `supervisor/main.py:626-633`
**Impact:** Medium - log file grows to 10MB before rotation

The endpoint reads all lines into memory then slices:

```python
# Before
with open(config.supervisor_log, "r") as f:
    all_lines = f.readlines()  # reads entire file (up to 10MB)
    return {"lines": all_lines[-lines:], "total": len(all_lines)}
```

Use `collections.deque` with maxlen or read from end of file:

```python
from collections import deque

with open(config.supervisor_log, "r") as f:
    recent = deque(f, maxlen=lines)
    return {"lines": list(recent), "total": lines}
```

---

## Fix 9: Batch/throttle database log inserts

**File:** `supervisor/main.py:917-922`, `supervisor/process.py:271-273`
**Impact:** Medium - every stdout/stderr line = 1 INSERT

Every log line from every service triggers a database INSERT via the log callback:

```python
LogEntry.create(service=service, level=level, message=message[:2000])
```

High-output services can generate hundreds of lines per second. Options:
- **Batch inserts**: Buffer log lines and bulk insert every 5 seconds
- **Rate-limit**: Only store every Nth line, or only error-level lines in the DB (stdout is already in log files)
- **Write-ahead only**: Skip DB for info-level, only store warnings/errors in SQLite

---

## Fix 10: Don't re-query `Service` on every log line

**File:** `supervisor/main.py:918-919`

The log callback queries the database for the service model on every single log line:

```python
service = Service.get_or_none(Service.name == service_name)
```

Cache service model references instead:

```python
_service_cache = {}

def log_callback(service_name, level, message):
    if service_name not in _service_cache:
        _service_cache[service_name] = Service.get_or_none(Service.name == service_name)
    service = _service_cache[service_name]
    if service:
        LogEntry.create(service=service, level=level, message=message[:2000])
    auto_fixer.on_log(service_name, level, message)
```

---

## Fix 11: Make `process_manager.restart()` non-blocking

**File:** `supervisor/process.py:199-203`
**Impact:** Low-medium - blocks API request for 5+ seconds

`restart()` calls `time.sleep(config.restart_delay)` which blocks the calling thread (and the async event loop if called from a route handler):

```python
def restart(self, service: Service) -> tuple[bool, str]:
    self.stop(service.name)
    time.sleep(config.restart_delay)  # blocks for 5 seconds!
    return self.start(service)
```

The restart endpoint at `main.py:388-399` calls this synchronously. Use `asyncio.sleep` or `run_in_executor`:

```python
# In main.py restart endpoint:
process_manager.stop(service.name)
await asyncio.sleep(config.restart_delay)
success, message = process_manager.start(service)
```

---

## Fix 12: Reduce crash monitor frequency from 10s to 30s

**File:** `supervisor/main.py:958-965`
**Impact:** Low

Crash detection every 10 seconds is unnecessarily frequent. 30 seconds is fine:

```python
await asyncio.sleep(30)
```

---

## Summary: Recommended Fix Order

| Priority | Fix | Effort | Impact |
|----------|-----|--------|--------|
| 1 | Fix 1: Cache metrics, don't compute live on status | Medium | Eliminates main bottleneck |
| 2 | Fix 3: Non-blocking `cpu_percent(interval=None)` | Trivial | Removes 0.1s * N blocking |
| 3 | Fix 2: Slow frontend poll to 10s | Trivial | 3x less server load |
| 4 | Fix 4: Cache disk usage | Low | Eliminates `os.walk` from hot path |
| 5 | Fix 10: Cache service model in log callback | Trivial | 1 less DB query per log line |
| 6 | Fix 5: Run monitor in executor | Low | Unblocks event loop |
| 7 | Fix 6+7: Slow log polling to 3-5s | Trivial | Less request volume |
| 8 | Fix 8: Tail log file instead of full read | Low | Avoids reading 10MB |
| 9 | Fix 9: Batch log inserts | Medium | Less DB write pressure |
| 10 | Fix 11: Async restart | Low | Unblocks 5s on restart |
| 11 | Fix 12: Crash monitor 30s | Trivial | Minor |

Fixes 1-4 together should resolve the majority of the responsiveness issues. Fix 1 alone is likely sufficient to make the dashboard feel snappy.
