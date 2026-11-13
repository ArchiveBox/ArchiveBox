from django.dispatch import Signal

# Bulk organization uses one UPDATE, so post_save cannot describe these changes.
# Receivers run after commit and receive snapshot_id / before / after dictionaries.
snapshot_folders_changed = Signal()
