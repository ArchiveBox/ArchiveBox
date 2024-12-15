# __package__ = 'archivebox.crawls'

# import time

# import abx
# import abx.archivebox.events
# import abx.hookimpl

# from datetime import datetime

# from django_stubs_ext.db.models import TypedModelMeta

# from django.db import models
# from django.db.models import Q
# from django.core.validators import MaxValueValidator, MinValueValidator 
# from django.conf import settings
# from django.utils import timezone
# from django.utils.functional import cached_property
# from django.urls import reverse_lazy

# from pathlib import Path

# # Glossary:
# #   - startup: when a new process is spawned
# #   - shutdown: when a process is exiting
# #   - start: at the beginning of some python code block
# #   - end: at the end of some python code block
# #   - queue: a django queryset of objects of a single type that are waiting to be processed
# #   - actor: a long-running daemon process that wakes up and processes a single object from a queue at a time
# #   - plugin: a python package that defines some hookimpls based on hookspecs exposed by ABX
# #   - object: an instance of a django model that represents a single row in the database


# # ORCHESTRATOR:
# # An orchestrator is a single long-running daemon process that manages spawning and killing actors for different queues of objects.
# # The orchestrator first starts when the archivebox starts, and it stops when archivebox is killed.
# # Only one orchestrator process can be running per collection per machine.
# # An orchestrator is aware of all of the ActorTypes that are defined in the system, and their associated queues.
# # When started, the orchestrator runs a single runloop that continues until the archivebox process is killed.
# # On each loop, the orchestrator:
# #   - loops through each ActorType defined in the system:
# #     - fetches the queue of objects pending for that ActorType by calling ActorType.get_queue()
# #     - check how many actors are currently running for that ActorType by calling current_actors = ActorType.get_running_actors()
# #     - determine how many new actors are needed and what their launch kwargs should be to process the objects in each queue
# #       actors_to_spawn = ActorType.get_actors_to_spawn(queue, current_actors)
# #       - e.g. if there is are 4 ArchiveResult objects queued all with the same persona + extractor, it should spawn a single actor to process all of them, if there are 4000 it should spawn ~5 actors
# #       - if there are 4 ArchiveResult objects queued with different personas + extractors, it should spawn a single actor for each persona + extractor
# #       - if there are *many* objects to process, it can spawn more actors of the same type up to ActorType.MAX_ACTORS to speed things up
# #     - spawns the new of actors needed as subprocesses ActorType.spawn_actors(actors_to_spawn, block=False, double_fork=False)
# #   - checks for ANY objects in the DB that have a retry_at time set but where no ActorType has them in their queue, and raises a warning that they are orphaned and will never be processed
# #   - sleeps for 0.1s before repeating the loop, to reduce the CPU load
# # The orchestrator does not manage killing actors, actors are expected to exit on their own when idle.
# # ABX defines the following hookspecs for plugins to hook into the orchestrator lifecycle:
# #   - abx.pm.hook.on_orchestrator_startup(all_actor_types)
# #   - abx.pm.hook.on_orchestrator_tick_started(all_actor_types, all_queues, all_running_actors)
# #   - abx.pm.hook.on_orchestrator_idle(all_actor_types)      # only run when there are no queues with pending objects to process
# #   - abx.pm.hook.on_orchestrator_shutdown(all_actor_types)

# # OBJECT:
# # e.g. Snapshot, Crawl, ArchiveResult
# # An object is a single row in a database table, defined by a django model.
# # An object has a finite set of states that it can be in.
# # An object has a status field that holds the object's current state e.g status="queued".
# # An object has a retry_at field that holds a timestamp for when it should next be checked by a actor eventloop.
# # Each type of object has a single tick() method defined that handles all of its state transitions.
# # When an object's retry_at time has passed, the actor managing that type of object will spwan an actor an call tick(object) to move it to its next state.
# # ABX defines the following hookspecs for plugins to hook into object lifecycle:  # use these for in-memory operations, dont use these for db on_create/on_update/on_delete logic, separate hooks are available on write operations below
# #   - abx.pm.hook.on_<objecttype>_init(object)    # when object is initialized in-memory, don't put any slow code here as it runs on every object returned from DB queries! only for setting default values, ._cache_attrs, etc.
# #   - abx.pm.hook.on_<objecttype>_clean(object)   # when object's form fields are validated but before it is to be saved to the DB, put any checks/validations on field values here
# #   - abx.pm.hook.on_<objecttype>_save(object)    # when object is being saved to the DB, put any code here that should run right before super().save()

# # ACTORS:
# # A actor is a long-running daemon process that runs a loop to process a single object at a time from a queue it defines (e.g. ActorType.queue=Snapshot.objects.filter(status='queued', retry_at__lte=time.now())).
# # An actor at runtime is an instance of an ActorType class + some launch kwargs that it's passed at startup (e.g. persona, extractor, etc.).
# # Actors are started lazily by the orchestrator only when their ActorType.queue indicates there are pending objects to process.
# # ActorTypes should define ActorType.get_queue(), ActorType.get_actors_to_spawn(), ActorType.get_running_actors(), and ActorType.spawn_actors() methods exposed to the orchestrator.
# # On startup, a actor can initialize shared resources it needs to perform its work, and keep a reference in memory to them. (e.g. launch chrome in the background, setup an API client, etc.)
# # On each loop, the actor gets a single object to process from the top of the queue, and runs ActorType.tick(object).
# # The actor should have a hardcoded ActorType.MAX_TICK_TIME, and should enforce it by killing the tick() method if it runs too long.
# # Before calling tick(), a actor should bump the object.retry_at time by MAX_TICK_TIME to prevent other actors from picking it up while the current actor is still processing it.
# # The actor blocks waiting for tick(obj) to finish executing, then the loop repeats and it gets the next object to call tick(object) on.
# # If a tick(obj) method raises an exception, the actor should catch it and log it, then move on to the next object in the queue.
# # If there are no objects left in the queue, the actor should exit.
# # On exit, a actor should release any shared resources it initialized on startup and clean up after itself.
# # On startup an actor should fire abx.pm.hook.on_actor_startup(object) and on exit it should fire abx.pm.hook.on_actor_exit(object) (both syncronous hooks that can be used by plugins to register any startup/cleanup code).
# # An ActorType defines the following hookspecs for plugins to hook into its behavior:
# #   - abx.pm.hook.on_actor_startup(actor, queue)
# #   - abx.pm.hook.on_actor_tick_start(actor, object)
# #   - abx.pm.hook.on_actor_tick_end(actor, object)
# #   - abx.pm.hook.on_actor_tick_exception(actor, object, exception)
# #   - abx.pm.hook.on_actor_shutdown(actor)

# # TICK:
# # A tick() method is a method defined on an ActorType, passed a single object to process and perform a single state transition on.
# # A tick() method does NOT need to lock the object its operating on, the actor will bump the object's retry_at += MAX_TICK_TIME before handing it off to tick().
# # A tick() method does NOT open a DB transaction for its entire duration of execution, instead it should do all its writes in one atomic operation using a compare-and-swap .select(status=previous_state).update(status=next_state) (optimistic concurrency control).
# # A tick() method does NOT return any values, it either succeeds and returns None, or fails and raises an exception to be handled by the actor runloop.
# # A tick() method does NOT need to enforce its own MAX_TICK_TIME / any timeouts, the actor runloop code should enforce that.
# # A tick() should NOT call other tick() methods directly, and it should not spawn orchestrator or actor processes.
# # A tick() should set its object.retry_at time to a value farther in the future and return early if it wants to skip execution due to hitting a ratelimit or transient error.
# # A tick() can:
# #   - read from any other objects, filesystem, or external APIs (e.g. check if snapshot_dir/screenshot.png exists)
# #   - perform any checks necessary and branch and determine what the transition it should perform to which next state
# #   - execute a single transition_from_abx_to_xyz(object) method to perform the transition to the next state it decided on

# # TRANSITION:
# # A transition_from_abx_to_xyz(object) method is a function defined on an ActorType, passed a single object by a tick() method to perform a defined transition on.
# # A transition_from_abx_to_xyz() method does NOT need to lock the object its operating on or open any db transactions.
# # A transiton should not have any branching logic, it should only execute the given transition that it defines + any side effects.
# # A transition should be indempotent, if two transitions run at once on the same object it should only perform one transition and the other should fail
# # A transition should be atomic, if it is interrupted it should leave the object in a consistent state
# # A transition's main body should:
# #   - perform a SINGLE write() to the underlying object using a compare_and_swap .filter(status=last_state).update(status=next_state) to move it to its next state
# #   - update the object's retry_at time to a new value, or set it to None if it's in a final state & should not be checked again
# # A transition can also trigger side effects at the end of its execution:
# #   - update the retry_at time on *other* objects (so that they are rechecked by their own actor on the next tick) (ONLY retry_at, do not update any other fields)
# #   - filesystem operations (e.g. moving a directory to a new location)
# #   - external API calls (e.g. uploading to s3, firing a webhook, writing to a logfile, etc.)
# #   - DO NOT use side effects to directly mutate other objects state or trigger other state transitions
# # ABX defines the following hookspecs for plugins to hook into transition behavior:
# #   - abx.pm.hook.on_transition_<objecttype>_from_abx_to_xyz_start(object)
# #   - abx.pm.hook.on_transition_<objecttype>_from_abx_to_xyz_end(object)

# # READ:
# # A read() method is a function defined for a given ActorType that performs a single read from the DB and/or other read models like django cache, filesystem, in-memory caches, etc.
# # A read() method should accept either an instance/pk/uuid/abid or some filter_kwargs, and return a benedict/TypedDict or pydantic model containing bare values as the result.

# # WRITE:
# # A write() method is a function defined for a given ActorType that performs a single atomic db write to update the DB, django cache, filesystem, in-memory caches, etc. for that object.
# # A write() method does NOT need to lock the object its operating on or open any db transactions, it should just perform a single compare-and-swap .select(status=last_state).update(status=next_state) operation.
# # A write() method does NOT need to enforce any timeouts or ratelimits, the tick() method should do that.
# # A write() method should NOT have any branching logic or side effects like spawning other processes.
# # ABX defines the following hookspecs for plugins to hook into write behavior:
# #   - abx.pm.hook.on_<objecttype>_created(object)
# #   - abx.pm.hook.on_<objecttype>_updated(object)
# #   - abx.pm.hook.on_<objecttype>_deleted(object)

# # SIDEEFFECT:
# # A sideeffect is a helper function defined in an app to be used by one or more tick() methods to perform a side effect that isn't a simple DB write or read.
# # A sideeffect can spawn other processes, make 3rd-party API calls, write to the filesystem, etc. e.g. subprocess.Popen('wget https://example.com')
# # A sideeffect should execute quickly and return early, it should try not to block for slow RPCs, subprocess jobs, or network operations.
# # For slow or long-running sideeffects, spawn a separate background process and return immediately. Update the object's retry_at time and state as-needed so that a future tick() will check for any expected output from the background job.
# # ABX defines the following hookspecs for plugins to hook into sideeffect behavior:
# #   - abx.pm.hook.on_sideeffect_xyz_started(object)
# #   - abx.pm.hook.on_sideeffect_xyz_succeeded(object)
# #   - abx.pm.hook.on_sideeffect_xyz_failed(object)



# # reads

# def tick_core():
#     tick_crawls()
#     tick_snapshots()
#     tick_archiveresults()
#     time.sleep(0.1)

# #################################################################################################################

# # [-> queued] -> started -> sealed

# SNAPSHOT_STATES = ('queued', 'started', 'sealed')
# SNAPSHOT_FINAL_STATES = ('sealed',)


# def get_snapshots_queue():
#     retry_at_reached = Q(retry_at__isnull=True) | Q(retry_at__lte=time.now())
#     not_in_final_state = ~Q(status__in=SNAPSHOT_FINAL_STATES)
#     queue = Snapshot.objects.filter(retry_at_reached & not_in_final_state)
#     return queue

# @djhuey.task(schedule=djhuey.Periodic(seconds=1))
# def tick_snapshots():
#     queue = get_snapshots_queue()
#     try:
#         snapshot = queue.last()
#         print(f'QUEUE LENGTH: {queue.count()}, PROCESSING SNAPSHOT[{snapshot.status}]: {snapshot}')
#         tick_snapshot(snapshot, cwd=snapshot.cwd)
#     except Snapshot.DoesNotExist:
#         pass


# def tick_snapshot(snapshot, config, cwd):
#     # [-> queued] -> started -> sealed

#     # SEALED (final state, do nothing)
#     if snapshot.status in SNAPSHOT_FINAL_STATES:
#         assert snapshot.retry_at is None
#         return None
#     else:
#         assert snapshot.retry_at is not None

#     # QUEUED -> PARTIAL
#     elif snapshot.status == 'queued':
#         transition_snapshot_to_started(snapshot, config, cwd)
    
#     # PARTIAL -> SEALED
#     elif snapshot.status == 'started':
#         if snapshot_has_pending_archiveresults(snapshot, config, cwd):
#             # tasks still in-progress, check back again in another 5s
#             snapshot.retry_at = time.now() + timedelta(seconds=5)
#             snapshot.save()
#         else:
#             # everything is finished, seal the snapshot
#             transition_snapshot_to_sealed(snapshot, config, cwd)
            
#     update_snapshot_index_json(archiveresult, config, cwd)
#     update_snapshot_index_html(archiveresult, config, cwd)


# def transition_snapshot_to_started(snapshot, config, cwd):
#     # queued [-> started] -> sealed
    
#     retry_at = time.now() + timedelta(seconds=10)
#     retries = snapshot.retries + 1
    
#     snapshot_to_update = {'pk': snapshot.pk, 'status': 'queued'}
#     fields_to_update = {'status': 'started', 'retry_at': retry_at, 'retries': retries, 'start_ts': time.now(), 'end_ts': None}
#     snapshot = abx.archivebox.writes.update_snapshot(filter_kwargs=snapshot_to_update, update_kwargs=fields_to_update)
    
#     # trigger side effects on state transition (these just emit an event to a separate queue thats then processed by a huey worker)
#     cleanup_snapshot_dir(snapshot, config, cwd)
#     create_snapshot_pending_archiveresults(snapshot, config, cwd)
#     update_snapshot_index_json(archiveresult, config, cwd)
#     update_snapshot_index_html(archiveresult, config, cwd)
    
    


# def transition_snapshot_to_sealed(snapshot, config, cwd):
#     # -> queued -> started [-> sealed]
    
#     snapshot_to_update = {'pk': snapshot.pk, 'status': 'started'}
#     fields_to_update = {'status': 'sealed', 'retry_at': None, 'end_ts': time.now()}
#     snapshot = abx.archivebox.writes.update_snapshot(filter_kwargs=snapshot_to_update, update_kwargs=fields_to_update)

#     # side effects:
#     cleanup_snapshot_dir(snapshot, config, cwd)
#     update_snapshot_index_json(snapshot, config, cwd)
#     update_snapshot_index_html(snapshot, config, cwd)
#     seal_snapshot_dir(snapshot, config, cwd)  # generate merkle tree and sign the snapshot
#     upload_snapshot_dir(snapshot, config, cwd)  # upload to s3, ipfs, etc
#     return snapshot


# def tick_crawl(crawl, config, cwd):
#     # [-> pending] -> archiving -> sealed
#     pass


# @abx.hookimpl
# def create_queued_archiveresult_on_snapshot(snapshot, config) -> bool | None:
#     # [-> queued] -> started -> succeeded
#     #                        -> backoff   -> queued
#     #                                     -> failed
#     if not config.SAVE_WARC:
#         return None
    
#     existing_results = abx.archivebox.reads.get_archiveresults_from_snapshot(snapshot, extractor='warc')
#     has_pending_or_succeeded_results = any(result.status in ('queued', 'started', 'succeeded', 'backoff') for result in existing_results)
#     if not has_pending_or_succeeded_results:
#         return abx.archivebox.writes.create_archiveresult(snapshot=snapshot, extractor='warc', status='queued', retry_at=time.now())
#     return None


# #################################################################################################################

# # [-> queued] -> started -> succeeded
# #                        -> backoff   -> queued
# #                                     -> failed

# ARCHIVERESULT_STATES = ('queued', 'started', 'succeeded', 'backoff', 'failed')
# ARCHIVERESULT_FINAL_STATES = ('succeeded', 'failed')


# def get_archiveresults_queue():
#     retry_at_reached = Q(retry_at__isnull=True) | Q(retry_at__lte=time.now())
#     not_in_final_state = ~Q(status__in=ARCHIVERESULT_FINAL_STATES)
#     queue = ArchiveResult.objects.filter(retry_at_reached & not_in_final_state)
#     return queue

# @djhuey.task(schedule=djhuey.Periodic(seconds=1))
# def tick_archiveresults():
#     queue = get_archiveresults_queue()
#     try:
#         archiveresult = queue.last()
#         print(f'QUEUE LENGTH: {queue.count()}, PROCESSING {archiveresult.status} ARCHIVERESULT: {archiveresult}')
#         tick_archiveresult(archiveresult, cwd=archiveresult.cwd)
#     except ArchiveResult.DoesNotExist:
#         pass

# def tick_archiveresult(archiveresult, cwd):
#     # [-> queued] -> started -> succeeded
#     #                        -> backoff   -> queued
#     #                                     -> failed
    
#     start_state = archiveresult.status

#     # SUCCEEDED or FAILED (final state, do nothing)
#     if archiveresult.status in ARCHIVERESULT_FINAL_STATES:
#         return None
    
#     # QUEUED -> STARTED
#     elif archiveresult.status == 'queued':
#         transition_archiveresult_to_started(archiveresult, config, cwd)
    
#     # STARTED -> SUCCEEDED or BACKOFF
#     elif archiveresult.status == 'started':
#         if check_if_extractor_succeeded(archiveresult, config, cwd):
#             transition_archiveresult_to_succeeded(archiveresult, config, cwd)
#         else:
#             transition_archiveresult_to_backoff(archiveresult, config, cwd)

#     # BACKOFF -> QUEUED or FAILED
#     elif archiveresult.status == 'backoff':
#         if too_many_retries(archiveresult, config):
#             transition_archiveresult_to_failed(archiveresult, config, cwd)
#         else:
#             transition_archiveresult_to_queued(archiveresult, config, cwd)
            
#     end_state = archiveresult.status
    
#     # trigger a tick on the Snapshot as well
#     archiveresult.snapshot.retry_at = time.now()
#     archiveresult.snapshot.save()

#     # trigger side effects on state transitions, e.g.:
#     #     queued -> started: create the extractor output dir, load extractor binary, spawn the extractor subprocess
#     #     started -> succeeded: cleanup the extractor output dir and move into snapshot.link_dir, write index.html, index.json, write logs
#     #     started -> backoff: cleanup the extractor output dir, wrtie index.html, index.json collect stdout/stderr logs
#     #     backoff -> queued: spawn the extractor subprocess later
#     #     *       -> *:      write index.html, index.json, bump ArchiveResult.updated and Snapshot.updated timestamps


# def transition_archiveresult_to_started(archiveresult, config, cwd):
#     # queued [-> started] -> succeeded
#     #                     -> backoff   -> queued
#     #                                  -> failed
    
#     from .extractors import WARC_EXTRACTOR
    
#     # ok, a warc ArchiveResult is queued, let's try to claim it
#     retry_at = time.now() + timedelta(seconds=config.TIMEOUT + 5)   # add 5sec buffer so we dont retry things if the previous task is doing post-task cleanup/saving thats taking a little longer than usual
#     retries = archiveresult.retries + 1
#     archiveresult_to_update = {'pk': archiveresult.pk, 'status': 'queued'}
#     fields_to_update = {'status': 'started', 'retry_at': retry_at, 'retries': retries, 'start_ts': time.now(), 'output': None, 'error': None}
#     archiveresult = abx.archivebox.writes.update_archiveresult(filter=archiveresult_to_update, update=fields_to_update)
    
#     # side effects:
#     with TimedProgress():
#         try:
#             from .extractors import WARC_EXTRACTOR
#             WARC_EXTRACTOR.cleanup_output_dir(archiveresult)
#             WARC_EXTRACTOR.load_extractor_binary(archiveresult)
#             WARC_EXTRACTOR.extract(archiveresult, config, cwd=archiveresult.cwd)
#         except Exception as e:
#             WARC_EXTRACTOR.save_error(archiveresult, e)
#         finally:
#             archiveresult_to_update = {'pk': archiveresult.pk, **fields_to_update}
#             fields_to_update = {'retry_at': time.now()}
#             archiveresult = abx.archivebox.writes.update_archiveresult(filter_kwargs=archiveresult_to_update, update_kwargs=fields_to_update)
    
#     return archiveresult


# def transition_archiveresult_to_succeeded(archiveresult, config, cwd):
#     output = abx.archivebox.reads.get_archiveresult_output(archiveresult)
#     end_ts = time.now()
    
#     archiveresult_to_update = {'pk': archiveresult.pk, 'status': 'started'}
#     fields_to_update = {'status': 'succeeded', 'retry_at': None, 'end_ts': end_ts, 'output': output}
#     archiveresult = abx.archivebox.writes.update_archiveresult(filter_kwargs=archiveresult_to_update, update_kwargs=fields_to_update)
#     return archiveresult


# def transition_archiveresult_to_backoff(archiveresult, config, cwd):
#     # queued -> started [-> backoff]   -> queued
#     #                                  -> failed
#     #                    -> succeeded
    
#     error = abx.archivebox.reads.get_archiveresult_error(archiveresult, cwd)
#     end_ts = time.now()
#     output = None
#     retry_at = time.now() + timedelta(seconds=config.TIMEOUT * archiveresult.retries)
    
#     archiveresult_to_update = {'pk': archiveresult.pk, 'status': 'started'}
#     fields_to_update = {'status': 'backoff', 'retry_at': retry_at, 'end_ts': end_ts, 'output': output, 'error': error}
#     archiveresult = abx.archivebox.writes.update_archiveresult(filter_kwargs=archiveresult_to_update, update_kwargs=fields_to_update)
#     return archiveresult


# def transition_archiveresult_to_queued(archiveresult, config, cwd):
#     # queued -> started -> backoff   [-> queued]
#     #                                 -> failed
#     #                   -> succeeded
    
#     archiveresult_to_update = {'pk': archiveresult.pk, 'status': 'backoff'}
#     fields_to_update = {'status': 'queued', 'retry_at': time.now(), 'start_ts': None, 'end_ts': None, 'output': None, 'error': None}
#     archiveresult = abx.archivebox.writes.update_archiveresult(filter_kwargs=archiveresult_to_update, update_kwargs=fields_to_update)
#     return archiveresult


# def transition_archiveresult_to_failed(archiveresult, config, cwd):
#     # queued -> started -> backoff    -> queued
#     #                                [-> failed]
#     #                   -> succeeded
    
#     archiveresult_to_update = {'pk': archiveresult.pk, 'status': 'backoff'}
#     fields_to_update = {'status': 'failed', 'retry_at': None}
#     archiveresult = abx.archivebox.writes.update_archiveresult(filter_kwargs=archiveresult_to_update, update_kwargs=fields_to_update)
#     return archiveresult





# def should_extract_wget(snapshot, extractor, config) -> bool | None:
#     if extractor == 'wget':
#         from .extractors import WGET_EXTRACTOR
#         return WGET_EXTRACTOR.should_extract(snapshot, config)

# def extrac_wget(uri, config, cwd):
#     from .extractors import WGET_EXTRACTOR
#     return WGET_EXTRACTOR.extract(uri, config, cwd)


# @abx.hookimpl
# def ready():
#     from .config import WGET_CONFIG
#     WGET_CONFIG.validate()

















# @abx.hookimpl
# def on_crawl_schedule_tick(crawl_schedule):
#     create_crawl_from_crawl_schedule_if_due(crawl_schedule)

# @abx.hookimpl
# def on_crawl_created(crawl):
#     create_root_snapshot(crawl)

# @abx.hookimpl
# def on_snapshot_created(snapshot, config):
#     create_snapshot_pending_archiveresults(snapshot, config)

# # events
# @abx.hookimpl
# def on_archiveresult_created(archiveresult):
#     abx.archivebox.exec.exec_archiveresult_extractor(archiveresult)

# @abx.hookimpl
# def on_archiveresult_updated(archiveresult):
#     abx.archivebox.writes.create_snapshots_pending_from_archiveresult_outlinks(archiveresult)




# def scheduler_runloop():
#     # abx.archivebox.events.on_scheduler_runloop_start(timezone.now(), machine=Machine.objects.get_current_machine())

#     while True:
#         # abx.archivebox.events.on_scheduler_tick_start(timezone.now(), machine=Machine.objects.get_current_machine())
        
#         scheduled_crawls = CrawlSchedule.objects.filter(is_enabled=True)
#         scheduled_crawls_due = scheduled_crawls.filter(next_run_at__lte=timezone.now())
        
#         for scheduled_crawl in scheduled_crawls_due:
#             try:
#                 abx.archivebox.events.on_crawl_schedule_tick(scheduled_crawl)
#             except Exception as e:
#                 abx.archivebox.events.on_crawl_schedule_tick_failure(timezone.now(), machine=Machine.objects.get_current_machine(), error=e, schedule=scheduled_crawl)
        
#         # abx.archivebox.events.on_scheduler_tick_end(timezone.now(), machine=Machine.objects.get_current_machine(), tasks=scheduled_tasks_due)
#         time.sleep(1)


# def create_crawl_from_ui_action(urls, extractor, credentials, depth, tags_str, persona, created_by, crawl_config):
#     if seed_is_remote(urls, extractor, credentials):
#         # user's seed is a remote source that will provide the urls (e.g. RSS feed URL, Pocket API, etc.)
#         uri, extractor, credentials = abx.archivebox.effects.check_remote_seed_connection(urls, extractor, credentials, created_by)
#     else:
#         # user's seed is some raw text they provided to parse for urls, save it to a file then load the file as a Seed
#         uri = abx.archivebox.writes.write_raw_urls_to_local_file(urls, extractor, tags_str, created_by)  # file:///data/sources/some_import.txt
    
#     seed = abx.archivebox.writes.get_or_create_seed(uri=remote_uri, extractor, credentials, created_by)
#     # abx.archivebox.events.on_seed_created(seed)
        
#     crawl = abx.archivebox.writes.create_crawl(seed=seed, depth=depth, tags_str=tags_str, persona=persona, created_by=created_by, config=crawl_config, schedule=None)
#     abx.archivebox.events.on_crawl_created(crawl)


# def create_crawl_from_crawl_schedule_if_due(crawl_schedule):
#     # make sure it's not too early to run this scheduled import (makes this function indepmpotent / safe to call multiple times / every second)
#     if timezone.now() < crawl_schedule.next_run_at:
#         # it's not time to run it yet, wait for the next tick
#         return
#     else:
#         # we're going to run it now, bump the next run time so that no one else runs it at the same time as us
#         abx.archivebox.writes.update_crawl_schedule_next_run_at(crawl_schedule, next_run_at=crawl_schedule.next_run_at + crawl_schedule.interval)
    
#     crawl_to_copy = None
#     try:
#         crawl_to_copy = crawl_schedule.crawl_set.first()  # alternatively use .last() to copy most recent crawl instead of very first crawl
#     except Crawl.DoesNotExist:
#         # there is no template crawl to base the next one off of
#         # user must add at least one crawl to a schedule that serves as the template for all future repeated crawls
#         return
    
#     new_crawl = abx.archivebox.writes.create_crawl_copy(crawl_to_copy=crawl_to_copy, schedule=crawl_schedule)
#     abx.archivebox.events.on_crawl_created(new_crawl)



# def create_root_snapshot(crawl):
#     # create a snapshot for the seed URI which kicks off the crawl
#     # only a single extractor will run on it, which will produce outlinks which get added back to the crawl
#     root_snapshot, created = abx.archivebox.writes.get_or_create_snapshot(crawl=crawl, url=crawl.seed.uri, config={
#         'extractors': (
#             abx.archivebox.reads.get_extractors_that_produce_outlinks()
#             if crawl.seed.extractor == 'auto' else
#             [crawl.seed.extractor]
#         ),
#         **crawl.seed.config,
#     })
#     if created:
#         abx.archivebox.events.on_snapshot_created(root_snapshot)
#         abx.archivebox.writes.update_crawl_stats(started_at=timezone.now())


# def create_snapshot_pending_archiveresults(snapshot, config):
#     config = get_scope_config(
#         # defaults=settings.CONFIG_FROM_DEFAULTS,
#         # configfile=settings.CONFIG_FROM_FILE,
#         # environment=settings.CONFIG_FROM_ENVIRONMENT,
#         persona=archiveresult.snapshot.crawl.persona,
#         seed=archiveresult.snapshot.crawl.seed,
#         crawl=archiveresult.snapshot.crawl,
#         snapshot=archiveresult.snapshot,
#         archiveresult=archiveresult,
#         # extra_config=extra_config,
#     )
    
#     extractors = abx.archivebox.reads.get_extractors_for_snapshot(snapshot, config)
#     for extractor in extractors:
#         archiveresult, created = abx.archivebox.writes.get_or_create_archiveresult_pending(
#             snapshot=snapshot,
#             extractor=extractor,
#             status='pending'
#         )
#         if created:
#             abx.archivebox.events.on_archiveresult_created(archiveresult)


# def exec_archiveresult_extractor(archiveresult):
#     config = get_scope_config(...)
    
#     # abx.archivebox.writes.update_archiveresult_started(archiveresult, start_ts=timezone.now())
#     # abx.archivebox.events.on_archiveresult_updated(archiveresult)
    
#     # check if it should be skipped
#     if not abx.archivebox.reads.get_archiveresult_should_run(archiveresult, config):
#         abx.archivebox.writes.update_archiveresult_skipped(archiveresult, status='skipped')
#         abx.archivebox.events.on_archiveresult_skipped(archiveresult, config)
#         return
    
#     # run the extractor method and save the output back to the archiveresult
#     try:
#         output = abx.archivebox.writes.exec_archiveresult_extractor(archiveresult, config)
#         abx.archivebox.writes.update_archiveresult_succeeded(archiveresult, output=output, error=None, end_ts=timezone.now())
#     except Exception as e:
#         abx.archivebox.writes.update_archiveresult_failed(archiveresult, error=e, end_ts=timezone.now())
    
#     # bump the modified time on the archiveresult and Snapshot
#     abx.archivebox.events.on_archiveresult_updated(archiveresult)
#     abx.archivebox.events.on_snapshot_updated(archiveresult.snapshot)
    

# def create_snapshots_pending_from_archiveresult_outlinks(archiveresult):
#     config = get_scope_config(...)
    
#     # check if extractor has finished succesfully, if not, dont bother checking for outlinks
#     if not archiveresult.status == 'succeeded':
#         return
    
#     # check if we have already reached the maximum recursion depth
#     hops_to_here = abx.archivebox.reads.get_outlink_parents(crawl_pk=archiveresult.snapshot.crawl_id, url=archiveresult.url, config=config)
#     if len(hops_to_here) >= archiveresult.crawl.max_depth +1:
#         return
    
#     # parse the output to get outlink url_entries
#     discovered_urls = abx.archivebox.reads.get_archiveresult_discovered_url_entries(archiveresult, config=config)
    
#     for url_entry in discovered_urls:
#         abx.archivebox.writes.create_outlink_record(src=archiveresult.snapshot.url, dst=url_entry.url, via=archiveresult)
#         abx.archivebox.writes.create_snapshot(crawl=archiveresult.snapshot.crawl, url_entry=url_entry)
        
#     # abx.archivebox.events.on_crawl_updated(archiveresult.snapshot.crawl)

# @abx.hookimpl.reads.get_outlink_parents
# def get_outlink_parents(url, crawl_pk=None, config=None):
#     scope = Q(dst=url)
#     if crawl_pk:
#         scope = scope | Q(via__snapshot__crawl_id=crawl_pk)
    
#     parent = list(Outlink.objects.filter(scope))
#     if not parent:
#         # base case: we reached the top of the chain, no more parents left
#         return []
    
#     # recursive case: there is another parent above us, get its parents
#     yield parent[0]
#     yield from get_outlink_parents(parent[0].src, crawl_pk=crawl_pk, config=config)


