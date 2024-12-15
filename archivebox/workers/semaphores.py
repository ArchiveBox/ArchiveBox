# import uuid
# from functools import wraps
# from django.db import connection, transaction
# from django.utils import timezone
# from huey.exceptions import TaskLockedException

# from archivebox.config import CONSTANTS

# class SqliteSemaphore:
#     def __init__(self, db_path, table_name, name, value=1, timeout=None):
#         self.db_path = db_path
#         self.table_name = table_name
#         self.name = name
#         self.value = value
#         self.timeout = timeout or 86400  # Set a max age for lock holders

#         # Ensure the table exists
#         with connection.cursor() as cursor:
#             cursor.execute(f"""
#                 CREATE TABLE IF NOT EXISTS {self.table_name} (
#                     id TEXT PRIMARY KEY,
#                     name TEXT,
#                     timestamp DATETIME
#                 )
#             """)

#     def acquire(self, name=None):
#         name = name or str(uuid.uuid4())
#         now = timezone.now()
#         expiration = now - timezone.timedelta(seconds=self.timeout)

#         with transaction.atomic():
#             # Remove expired locks
#             with connection.cursor() as cursor:
#                 cursor.execute(f"""
#                     DELETE FROM {self.table_name}
#                     WHERE name = %s AND timestamp < %s
#                 """, [self.name, expiration])

#             # Try to acquire the lock
#             with connection.cursor() as cursor:
#                 cursor.execute(f"""
#                     INSERT INTO {self.table_name} (id, name, timestamp)
#                     SELECT %s, %s, %s
#                     WHERE (
#                         SELECT COUNT(*) FROM {self.table_name}
#                         WHERE name = %s
#                     ) < %s
#                 """, [name, self.name, now, self.name, self.value])

#                 if cursor.rowcount > 0:
#                     return name

#         # If we couldn't acquire the lock, remove our attempted entry
#         with connection.cursor() as cursor:
#             cursor.execute(f"""
#                 DELETE FROM {self.table_name}
#                 WHERE id = %s AND name = %s
#             """, [name, self.name])

#         return None

#     def release(self, name):
#         with connection.cursor() as cursor:
#             cursor.execute(f"""
#                 DELETE FROM {self.table_name}
#                 WHERE id = %s AND name = %s
#             """, [name, self.name])
#         return cursor.rowcount > 0


# LOCKS_DB_PATH = CONSTANTS.DATABASE_FILE.parent / 'locks.sqlite3'


# def lock_task_semaphore(db_path, table_name, lock_name, value=1, timeout=None):
#     """
#     Lock which can be acquired multiple times (default = 1).

#     NOTE: no provisions are made for blocking, waiting, or notifying. This is
#     just a lock which can be acquired a configurable number of times.

#     Example:

#     # Allow up to 3 workers to run this task concurrently. If the task is
#     # locked, retry up to 2 times with a delay of 60s.
#     @huey.task(retries=2, retry_delay=60)
#     @lock_task_semaphore('path/to/db.sqlite3', 'semaphore_locks', 'my-lock', 3)
#     def my_task():
#         ...
#     """
#     sem = SqliteSemaphore(db_path, table_name, lock_name, value, timeout)
#     def decorator(fn):
#         @wraps(fn)
#         def inner(*args, **kwargs):
#             tid = sem.acquire()
#             if tid is None:
#                 raise TaskLockedException(f'unable to acquire lock {lock_name}')
#             try:
#                 return fn(*args, **kwargs)
#             finally:
#                 sem.release(tid)
#         return inner
#     return decorator
