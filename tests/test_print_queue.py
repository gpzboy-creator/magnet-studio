"""PrintQueueController on its own: no window, no printer – a fake worker plays the printer."""
from PyQt6.QtCore import QObject, pyqtSignal

import pytest

from magnetstudio.core.print_jobs import PrintJob, PrintMode
from magnetstudio.services.print_queue import PrintQueueController, Stage


class FakeWorker(QObject):
    """Stands in for PrintWorker. Finishes when the test calls .finish()."""
    status = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)
    finished = pyqtSignal()
    running: list["FakeWorker"] = []

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job, self.cancelled = job, False

    def start(self):
        FakeWorker.running.append(self)

    def finish(self, ok=True, msg=""):
        self.progress.emit(0, 1)
        self.progress.emit(1, 1)
        (self.succeeded if ok else self.failed).emit(msg or ("ok" if ok else "נכשל"))
        FakeWorker.running.remove(self)
        self.finished.emit()

    def cancel(self):
        self.cancelled = True

    def wait(self, _ms):
        return True


@pytest.fixture
def ctl(qapp):
    FakeWorker.running = []
    jobs = []

    def factory(item, copies):
        job = PrintJob(mode=PrintMode.THERMAL, printer_name="P1", photo_paths=[item.path],
                       copies=copies, tag=item.id)
        jobs.append(job)
        return job

    c = PrintQueueController(factory, total_printed=100, worker_cls=FakeWorker,
                             printer_check=lambda name: name == "P1")
    c.events = []
    c.item_changed.connect(lambda i: c.events.append((i, c.items[i].stage)))
    c.busy_changed.connect(lambda b: c.events.append(("busy", b)))
    c.made_jobs = jobs
    return c


def test_stage_flow_and_counters(ctl):
    a = ctl.add_photo("/x/a.jpg")
    assert a.stage == Stage.INCOMING and not ctl.is_busy
    assert ctl.print_item(a.id, copies=2)
    assert ctl.is_busy and a.stage == Stage.COMPOSING and a.jobs_open == 1
    FakeWorker.running[0].finish()
    stages = [s for i, s in ctl.events if i == a.id]
    assert stages == [Stage.COMPOSING, Stage.COMPOSING, Stage.SPOOLING, Stage.PRINTED]
    assert a.copies_printed == 2 and a.jobs_open == 0
    assert (ctl.session_printed, ctl.total_printed) == (2, 102)
    assert ctl.events[-1] == ("busy", False) and not ctl.is_busy


def test_jobs_run_one_at_a_time_in_order(ctl):
    a, b = ctl.add_photo("/x/a.jpg"), ctl.add_photo("/x/b.jpg")
    ctl.print_item(a.id)
    ctl.print_item(b.id)
    ctl.print_item(a.id)                       # extra copy while the first job runs
    assert len(FakeWorker.running) == 1 and ctl.waiting == 2
    assert b.stage == Stage.QUEUED and a.jobs_open == 2
    FakeWorker.running[0].finish()             # a #1 done → a still has a job waiting
    assert a.stage == Stage.QUEUED and a.copies_printed == 1
    assert FakeWorker.running[0].job.tag == b.id and b.stage == Stage.COMPOSING
    FakeWorker.running[0].finish()
    FakeWorker.running[0].finish()
    assert a.stage == b.stage == Stage.PRINTED and a.copies_printed == 2
    assert [e for e in ctl.events if e[0] == "busy"] == [("busy", True), ("busy", False)]


def test_no_duplicate_on_fast_double_tap(ctl):
    a = ctl.add_photo("/x/a.jpg")
    assert ctl.print_item(a.id, allow_duplicate=False)
    assert not ctl.print_item(a.id, allow_duplicate=False), "already in flight"
    assert ctl.print_item(a.id), "explicit extra copy is allowed"
    assert len(ctl.made_jobs) == 2


def test_failure_marks_item_and_continues(ctl):
    a, b = ctl.add_photo("/x/a.jpg"), ctl.add_photo("/x/b.jpg")
    failed = []
    ctl.job_failed.connect(failed.append)
    ctl.print_item(a.id)
    ctl.print_item(b.id)
    FakeWorker.running[0].finish(ok=False, msg="נייר נתקע")
    assert a.stage == Stage.FAILED and a.error == "נייר נתקע" and failed == ["נייר נתקע"]
    assert ctl.total_printed == 100, "failed job is not counted"
    FakeWorker.running[0].finish()
    assert b.stage == Stage.PRINTED and ctl.total_printed == 101


def test_unavailable_printer(ctl):
    a = ctl.add_photo("/x/a.jpg")
    stale = []
    ctl.printer_unavailable.connect(stale.append)
    job = PrintJob(mode=PrintMode.THERMAL, printer_name="Gone", photo_paths=[a.path], tag=a.id)
    assert ctl.submit(job) is False
    assert a.stage == Stage.FAILED and stale == ["Gone"] and not ctl.is_busy and ctl.waiting == 0


def test_shutdown_drops_waiting_and_cancels(ctl):
    a = ctl.add_photo("/x/a.jpg")
    for _ in range(3):
        ctl.print_item(a.id)
    w = FakeWorker.running[0]
    ctl.shutdown()
    assert ctl.waiting == 0 and w.cancelled


def test_window_only_displays(qapp):
    """MainWindow keeps no queue state of its own – it reads the controller's."""
    from magnetstudio.core.settings import load_settings
    from magnetstudio.ui.main_window import MainWindow
    win = MainWindow(load_settings())
    try:
        for attr in ("_queue", "_worker", "_active_job", "_session_count"):
            assert not hasattr(win, attr), attr
        item = win.add_photo(__file__, "manual", select=False)
        assert win.items is win.queue.items and item.id in win.queue_panel.cards
        win.queue._set_stage(item, Stage.QUEUED)
        assert win.queue_panel.cards[item.id].status.name == "INCOMING"
        item.copies_printed = 1
        win.queue._set_stage(item, Stage.QUEUED)
        assert win.queue_panel.cards[item.id].status.name == "SPOOLING", "queued reprint shows as spooling"
    finally:
        win.close()          # closeEvent removes the app-wide key filter and stops the queue
