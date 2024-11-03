from statemachine import State, StateMachine
from django.db import models
from multiprocessing import Process
import psutil
import time

# State Machine Definitions
#################################################

class SnapshotMachine(StateMachine):
    """State machine for managing Snapshot lifecycle."""
    
    # States
    queued = State(initial=True)
    started = State()
    sealed = State(final=True)
    
    # Transitions
    start = queued.to(started, cond='can_start')
    seal = started.to(sealed, cond='is_finished')
    
    # Events
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished') |
        started.to(sealed, cond='is_finished')
    )
    
    def __init__(self, snapshot):
        self.snapshot = snapshot
        super().__init__()
        
    def can_start(self):
        return True
        
    def is_finished(self):
        return not self.snapshot.has_pending_archiveresults()
        
    def before_start(self):
        """Pre-start validation and setup."""
        self.snapshot.cleanup_dir()
        
    def after_start(self):
        """Post-start side effects."""
        self.snapshot.create_pending_archiveresults()
        self.snapshot.update_indices()
        self.snapshot.bump_retry_at(seconds=10)
        
    def before_seal(self):
        """Pre-seal validation and cleanup."""
        self.snapshot.cleanup_dir()
        
    def after_seal(self):
        """Post-seal actions."""
        self.snapshot.update_indices()
        self.snapshot.seal_dir()
        self.snapshot.upload_dir()
        self.snapshot.retry_at = None
        self.snapshot.save()


class ArchiveResultMachine(StateMachine):
    """State machine for managing ArchiveResult lifecycle."""
    
    # States
    queued = State(initial=True)
    started = State()
    succeeded = State(final=True)
    backoff = State()
    failed = State(final=True)
    
    # Transitions
    start = queued.to(started, cond='can_start')
    succeed = started.to(succeeded, cond='extractor_succeeded')
    backoff = started.to(backoff, unless='extractor_succeeded')
    retry = backoff.to(queued, cond='can_retry')
    fail = backoff.to(failed, unless='can_retry')
    
    # Events
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to.itself(cond='extractor_still_running') |
        started.to(succeeded, cond='extractor_succeeded') |
        started.to(backoff, unless='extractor_succeeded') |
        backoff.to.itself(cond='still_waiting_to_retry') |
        backoff.to(queued, cond='can_retry') |
        backoff.to(failed, unless='can_retry')
    )
    
    def __init__(self, archiveresult):
        self.archiveresult = archiveresult
        super().__init__()
    
    def can_start(self):
        return True
    
    def extractor_still_running(self):
        return self.archiveresult.start_ts > time.now() - timedelta(seconds=5)
    
    def extractor_succeeded(self):
        # return check_if_extractor_succeeded(self.archiveresult)
        return self.archiveresult.start_ts < time.now() - timedelta(seconds=5)
    
    def can_retry(self):
        return self.archiveresult.retries < self.archiveresult.max_retries
        
    def before_start(self):
        """Pre-start initialization."""
        self.archiveresult.retries += 1
        self.archiveresult.start_ts = time.now()
        self.archiveresult.output = None
        self.archiveresult.error = None
        
    def after_start(self):
        """Post-start execution."""
        self.archiveresult.bump_retry_at(seconds=self.archiveresult.timeout + 5)
        execute_extractor(self.archiveresult)
        self.archiveresult.snapshot.bump_retry_at(seconds=5)
        
    def before_succeed(self):
        """Pre-success validation."""
        self.archiveresult.output = get_archiveresult_output(self.archiveresult)
        
    def after_succeed(self):
        """Post-success cleanup."""
        self.archiveresult.end_ts = time.now()
        self.archiveresult.retry_at = None
        self.archiveresult.update_indices()
        
    def before_backoff(self):
        """Pre-backoff error capture."""
        self.archiveresult.error = get_archiveresult_error(self.archiveresult)
        
    def after_backoff(self):
        """Post-backoff retry scheduling."""
        self.archiveresult.end_ts = time.now()
        self.archiveresult.bump_retry_at(
            seconds=self.archiveresult.timeout * self.archiveresult.retries
        )
        self.archiveresult.update_indices()
        
    def before_fail(self):
        """Pre-failure finalization."""
        self.archiveresult.retry_at = None
        
    def after_fail(self):
        """Post-failure cleanup."""
        self.archiveresult.update_indices()

# Models
#################################################

class Snapshot(models.Model):
    status = models.CharField(max_length=32, default='queued')
    retry_at = models.DateTimeField(null=True)
    
    @property
    def sm(self):
        """Get the state machine for this snapshot."""
        return SnapshotMachine(self)
    
    def has_pending_archiveresults(self):
        return self.archiveresult_set.exclude(
            status__in=['succeeded', 'failed']
        ).exists()
    
    def bump_retry_at(self, seconds):
        self.retry_at = time.now() + timedelta(seconds=seconds)
        self.save()
        
    def cleanup_dir(self):
        cleanup_snapshot_dir(self)
        
    def create_pending_archiveresults(self):
        create_snapshot_pending_archiveresults(self)
        
    def update_indices(self):
        update_snapshot_index_json(self)
        update_snapshot_index_html(self)
        
    def seal_dir(self):
        seal_snapshot_dir(self)
        
    def upload_dir(self):
        upload_snapshot_dir(self)


class ArchiveResult(models.Model):
    snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE)
    status = models.CharField(max_length=32, default='queued')
    retry_at = models.DateTimeField(null=True)
    retries = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)
    timeout = models.IntegerField(default=60)
    start_ts = models.DateTimeField(null=True)
    end_ts = models.DateTimeField(null=True)
    output = models.TextField(null=True)
    error = models.TextField(null=True)
    
    def get_machine(self):
        return ArchiveResultMachine(self)
    
    def bump_retry_at(self, seconds):
        self.retry_at = time.now() + timedelta(seconds=seconds)
        self.save()
        
    def update_indices(self):
        update_archiveresult_index_json(self)
        update_archiveresult_index_html(self)


# Actor System
#################################################

class BaseActor:
    MAX_TICK_TIME = 60
    
    def tick(self, obj):
        """Process a single object through its state machine."""
        machine = obj.get_machine()
        
        if machine.is_queued:
            if machine.can_start():
                machine.start()
                
        elif machine.is_started:
            if machine.can_seal():
                machine.seal()
                
        elif machine.is_backoff:
            if machine.can_retry():
                machine.retry()
            else:
                machine.fail()


class Orchestrator:
    """Main orchestrator that manages all actors."""
    
    def __init__(self):
        self.pid = None
        
    @classmethod
    def spawn(cls):
        orchestrator = cls()
        proc = Process(target=orchestrator.runloop)
        proc.start()
        return proc.pid
        
    def runloop(self):
        self.pid = os.getpid()
        abx.pm.hook.on_orchestrator_startup(self)
        
        try:
            while True:
                self.process_queue(Snapshot)
                self.process_queue(ArchiveResult)
                time.sleep(0.1)
                
        except (KeyboardInterrupt, SystemExit):
            abx.pm.hook.on_orchestrator_shutdown(self)
            
    def process_queue(self, model):
        retry_at_reached = Q(retry_at__isnull=True) | Q(retry_at__lte=time.now())
        queue = model.objects.filter(retry_at_reached)
        
        if queue.exists():
            actor = BaseActor()
            for obj in queue:
                try:
                    with transaction.atomic():
                        actor.tick(obj)
                except Exception as e:
                    abx.pm.hook.on_actor_tick_exception(actor, obj, e)


# Periodic Tasks
#################################################

@djhuey.periodic_task(schedule=djhuey.crontab(minute='*'))
def ensure_orchestrator_running():
    """Ensure orchestrator is running, start if not."""
    if not any(p.name().startswith('Orchestrator') for p in psutil.process_iter()):
        Orchestrator.spawn()
