// ArchiveBox Schema - Drizzle ORM (READABLE VERSION)
// Improved formatting for better readability
// Line count: ~380 lines (slightly longer but MUCH easier to read)

import { pgTable, uuid, varchar, text, boolean, timestamp, smallint, integer, json, unique, index } from 'drizzle-orm/pg-core';
import { relations } from 'drizzle-orm';
import { uuidv7 } from 'uuidv7';

// ============================================
// HELPERS - Reusable field patterns
// ============================================

const uuidv7Default = () => uuidv7();

// Common field patterns to reduce repetition
const id_field = () => uuid('id').primaryKey().$defaultFn(uuidv7Default);
const abid_field = () => varchar('abid', { length: 30 }).unique().notNull();
const created_at_field = () => timestamp('created_at', { withTimezone: true }).defaultNow().notNull();
const modified_at_field = () => timestamp('modified_at', { withTimezone: true }).defaultNow().notNull();
const notes_field = () => text('notes').default('').notNull();

const health_fields = () => ({
  num_uses_failed: integer('num_uses_failed').default(0).notNull(),
  num_uses_succeeded: integer('num_uses_succeeded').default(0).notNull(),
});

const state_machine_fields = () => ({
  status: varchar('status', { length: 16 }).default('queued').notNull(),
  retry_at: timestamp('retry_at', { withTimezone: true }).defaultNow().notNull(),
});

// ============================================
// USER TABLE
// ============================================

export const users = pgTable('auth_user', {
  // Primary Key
  id: id_field(),

  // Core Auth Fields
  username: varchar('username', { length: 150 })
    .unique()
    .notNull(),

  email: varchar('email', { length: 254 })
    .notNull(),

  password: varchar('password', { length: 128 })
    .notNull(),

  // Profile Fields
  first_name: varchar('first_name', { length: 150 })
    .notNull(),

  last_name: varchar('last_name', { length: 150 })
    .notNull(),

  // Permission Flags
  is_active: boolean('is_active')
    .default(true)
    .notNull(),

  is_staff: boolean('is_staff')
    .default(false)
    .notNull(),

  is_superuser: boolean('is_superuser')
    .default(false)
    .notNull(),

  // Timestamps
  date_joined: timestamp('date_joined', { withTimezone: true })
    .defaultNow()
    .notNull(),

  last_login: timestamp('last_login', { withTimezone: true }),

}, (table) => ({
  // Indexes
  usernameIdx: index('auth_user_username_idx').on(table.username),
}));

export const usersRelations = relations(users, ({ many }) => ({
  tags: many(tags),
  kv_tags: many(kv_tags),
  seeds: many(seeds),
  crawls: many(crawls),
  crawl_schedules: many(crawl_schedules),
  snapshots: many(snapshots),
  archive_results: many(archive_results),
}));

// ============================================
// TAG TABLE (Old-style tags)
// ============================================

export const tags = pgTable('core_tag', {
  // Primary Key & ABID
  id: id_field(),
  abid: abid_field(),

  // Timestamps
  created_at: created_at_field(),
  modified_at: modified_at_field(),

  // Foreign Keys
  created_by_id: uuid('created_by_id')
    .notNull()
    .references(() => users.id, { onDelete: 'cascade' }),

  // Data Fields
  name: varchar('name', { length: 100 })
    .unique()
    .notNull(),

  slug: varchar('slug', { length: 100 })
    .unique()
    .notNull(),

}, (table) => ({
  // Indexes
  createdAtIdx: index('core_tag_created_at_idx').on(table.created_at),
  createdByIdx: index('core_tag_created_by_idx').on(table.created_by_id),
  abidIdx: index('core_tag_abid_idx').on(table.abid),
}));

export const tagsRelations = relations(tags, ({ one, many }) => ({
  created_by: one(users, {
    fields: [tags.created_by_id],
    references: [users.id],
  }),
  snapshots: many(snapshot_tags),
}));

// ============================================
// KVTAG TABLE (Key-value tags)
// ============================================

export const kv_tags = pgTable('core_kvtags', {
  // Primary Key
  id: id_field(),

  // Timestamps
  created_at: created_at_field(),

  // Tag Data
  name: varchar('name', { length: 255 })
    .notNull(),

  value: text('value'),

  // Generic Foreign Key (handled in app logic)
  obj_type: varchar('obj_type', { length: 100 })
    .notNull(),

  obj_id: uuid('obj_id')
    .notNull(),

}, (table) => ({
  // Constraints
  uniqueObjTag: unique().on(table.obj_id, table.name),

  // Indexes
  createdAtIdx: index('core_kvtags_created_at_idx').on(table.created_at),
  objTypeIdx: index('core_kvtags_obj_type_idx').on(table.obj_type),
  objIdIdx: index('core_kvtags_obj_id_idx').on(table.obj_id),
}));

export const kv_tagsRelations = relations(kv_tags, ({ one }) => ({
  // Generic foreign key - handled in application logic
}));

// ============================================
// SEED TABLE
// ============================================

export const seeds = pgTable('crawls_seed', {
  // Primary Key & ABID
  id: id_field(),
  abid: abid_field(),

  // Timestamps
  created_at: created_at_field(),
  modified_at: modified_at_field(),

  // Foreign Keys
  created_by_id: uuid('created_by_id')
    .notNull()
    .references(() => users.id, { onDelete: 'cascade' }),

  // Source Configuration
  uri: text('uri')
    .notNull(),

  extractor: varchar('extractor', { length: 32 })
    .default('auto')
    .notNull(),

  tags_str: varchar('tags_str', { length: 255 })
    .default('')
    .notNull(),

  label: varchar('label', { length: 255 })
    .default('')
    .notNull(),

  config: json('config')
    .default({})
    .notNull(),

  // Storage
  output_dir: varchar('output_dir', { length: 255 })
    .default('')
    .notNull(),

  // Metadata
  notes: notes_field(),

  // Health Tracking
  ...health_fields(),

}, (table) => ({
  // Constraints
  uniqueUserUriExtractor: unique().on(
    table.created_by_id,
    table.uri,
    table.extractor
  ),
  uniqueUserLabel: unique().on(
    table.created_by_id,
    table.label
  ),

  // Indexes
  createdAtIdx: index('crawls_seed_created_at_idx').on(table.created_at),
  createdByIdx: index('crawls_seed_created_by_idx').on(table.created_by_id),
  abidIdx: index('crawls_seed_abid_idx').on(table.abid),
}));

export const seedsRelations = relations(seeds, ({ one, many }) => ({
  created_by: one(users, {
    fields: [seeds.created_by_id],
    references: [users.id],
  }),
  crawls: many(crawls),
}));

// ============================================
// CRAWL SCHEDULE TABLE
// ============================================

export const crawl_schedules = pgTable('crawls_crawlschedule', {
  // Primary Key & ABID
  id: id_field(),
  abid: abid_field(),

  // Timestamps
  created_at: created_at_field(),
  modified_at: modified_at_field(),

  // Foreign Keys
  created_by_id: uuid('created_by_id')
    .notNull()
    .references(() => users.id, { onDelete: 'cascade' }),

  template_id: uuid('template_id')
    .notNull()
    .references(() => crawls.id, { onDelete: 'cascade' }),

  // Schedule Configuration
  schedule: varchar('schedule', { length: 64 })
    .notNull(),

  is_enabled: boolean('is_enabled')
    .default(true)
    .notNull(),

  label: varchar('label', { length: 64 })
    .default('')
    .notNull(),

  // Metadata
  notes: notes_field(),

  // Health Tracking
  ...health_fields(),

}, (table) => ({
  // Indexes
  createdAtIdx: index('crawls_crawlschedule_created_at_idx').on(table.created_at),
  createdByIdx: index('crawls_crawlschedule_created_by_idx').on(table.created_by_id),
  templateIdx: index('crawls_crawlschedule_template_idx').on(table.template_id),
  abidIdx: index('crawls_crawlschedule_abid_idx').on(table.abid),
}));

export const crawl_schedulesRelations = relations(crawl_schedules, ({ one, many }) => ({
  created_by: one(users, {
    fields: [crawl_schedules.created_by_id],
    references: [users.id],
  }),
  template: one(crawls, {
    fields: [crawl_schedules.template_id],
    references: [crawls.id],
  }),
  crawls: many(crawls),
}));

// ============================================
// CRAWL TABLE
// ============================================

export const crawls = pgTable('crawls_crawl', {
  // Primary Key & ABID
  id: id_field(),
  abid: abid_field(),

  // Timestamps
  created_at: created_at_field(),
  modified_at: modified_at_field(),

  // Foreign Keys
  created_by_id: uuid('created_by_id')
    .notNull()
    .references(() => users.id, { onDelete: 'cascade' }),

  seed_id: uuid('seed_id')
    .notNull()
    .references(() => seeds.id, { onDelete: 'restrict' }),

  schedule_id: uuid('schedule_id')
    .references(() => crawl_schedules.id, { onDelete: 'set null' }),

  // Crawl Data
  urls: text('urls')
    .default('')
    .notNull(),

  config: json('config')
    .default({})
    .notNull(),

  max_depth: smallint('max_depth')
    .default(0)
    .notNull(),

  tags_str: varchar('tags_str', { length: 1024 })
    .default('')
    .notNull(),

  persona_id: uuid('persona_id'),

  label: varchar('label', { length: 64 })
    .default('')
    .notNull(),

  // Storage
  output_dir: varchar('output_dir', { length: 255 })
    .default('')
    .notNull(),

  // Metadata
  notes: notes_field(),

  // State Machine
  ...state_machine_fields(),

  // Health Tracking
  ...health_fields(),

}, (table) => ({
  // Indexes
  createdAtIdx: index('crawls_crawl_created_at_idx').on(table.created_at),
  createdByIdx: index('crawls_crawl_created_by_idx').on(table.created_by_id),
  seedIdx: index('crawls_crawl_seed_idx').on(table.seed_id),
  scheduleIdx: index('crawls_crawl_schedule_idx').on(table.schedule_id),
  statusIdx: index('crawls_crawl_status_idx').on(table.status),
  retryAtIdx: index('crawls_crawl_retry_at_idx').on(table.retry_at),
  abidIdx: index('crawls_crawl_abid_idx').on(table.abid),
}));

export const crawlsRelations = relations(crawls, ({ one, many }) => ({
  created_by: one(users, {
    fields: [crawls.created_by_id],
    references: [users.id],
  }),
  seed: one(seeds, {
    fields: [crawls.seed_id],
    references: [seeds.id],
  }),
  schedule: one(crawl_schedules, {
    fields: [crawls.schedule_id],
    references: [crawl_schedules.id],
  }),
  snapshots: many(snapshots),
  outlinks: many(outlinks),
}));

// ============================================
// SNAPSHOT TABLE
// ============================================

export const snapshots = pgTable('core_snapshot', {
  // Primary Key & ABID
  id: id_field(),
  abid: abid_field(),

  // Timestamps
  created_at: created_at_field(),
  modified_at: modified_at_field(),

  // Foreign Keys
  created_by_id: uuid('created_by_id')
    .notNull()
    .references(() => users.id, { onDelete: 'cascade' }),

  crawl_id: uuid('crawl_id')
    .references(() => crawls.id, { onDelete: 'cascade' }),

  // URL Data
  url: text('url')
    .unique()
    .notNull(),

  timestamp: varchar('timestamp', { length: 32 })
    .unique()
    .notNull(),

  bookmarked_at: timestamp('bookmarked_at', { withTimezone: true })
    .notNull(),

  // Content Metadata
  title: varchar('title', { length: 512 }),

  downloaded_at: timestamp('downloaded_at', { withTimezone: true }),

  config: json('config')
    .default({})
    .notNull(),

  // Storage
  output_dir: varchar('output_dir', { length: 255 }),

  // Metadata
  notes: notes_field(),

  // State Machine
  ...state_machine_fields(),

  // Health Tracking
  ...health_fields(),

}, (table) => ({
  // Indexes
  createdAtIdx: index('core_snapshot_created_at_idx').on(table.created_at),
  createdByIdx: index('core_snapshot_created_by_idx').on(table.created_by_id),
  crawlIdx: index('core_snapshot_crawl_idx').on(table.crawl_id),
  urlIdx: index('core_snapshot_url_idx').on(table.url),
  timestampIdx: index('core_snapshot_timestamp_idx').on(table.timestamp),
  bookmarkedAtIdx: index('core_snapshot_bookmarked_at_idx').on(table.bookmarked_at),
  downloadedAtIdx: index('core_snapshot_downloaded_at_idx').on(table.downloaded_at),
  titleIdx: index('core_snapshot_title_idx').on(table.title),
  statusIdx: index('core_snapshot_status_idx').on(table.status),
  retryAtIdx: index('core_snapshot_retry_at_idx').on(table.retry_at),
  abidIdx: index('core_snapshot_abid_idx').on(table.abid),
}));

export const snapshotsRelations = relations(snapshots, ({ one, many }) => ({
  created_by: one(users, {
    fields: [snapshots.created_by_id],
    references: [users.id],
  }),
  crawl: one(crawls, {
    fields: [snapshots.crawl_id],
    references: [crawls.id],
  }),
  tags: many(snapshot_tags),
  archive_results: many(archive_results),
}));

// ============================================
// ARCHIVE RESULT TABLE
// ============================================

export const archive_results = pgTable('core_archiveresult', {
  // Primary Key & ABID
  id: id_field(),
  abid: abid_field(),

  // Timestamps
  created_at: created_at_field(),
  modified_at: modified_at_field(),

  // Foreign Keys
  created_by_id: uuid('created_by_id')
    .notNull()
    .references(() => users.id, { onDelete: 'cascade' }),

  snapshot_id: uuid('snapshot_id')
    .notNull()
    .references(() => snapshots.id, { onDelete: 'cascade' }),

  // Extraction Data
  extractor: varchar('extractor', { length: 32 })
    .notNull(),

  pwd: varchar('pwd', { length: 256 }),

  cmd: json('cmd'),

  cmd_version: varchar('cmd_version', { length: 128 }),

  output: varchar('output', { length: 1024 }),

  // Execution Timing
  start_ts: timestamp('start_ts', { withTimezone: true }),
  end_ts: timestamp('end_ts', { withTimezone: true }),

  // Storage
  output_dir: varchar('output_dir', { length: 256 }),

  iface_id: uuid('iface_id'),

  // Metadata
  notes: notes_field(),

  // State Machine
  ...state_machine_fields(),

  // Health Tracking
  ...health_fields(),

}, (table) => ({
  // Indexes
  createdAtIdx: index('core_archiveresult_created_at_idx').on(table.created_at),
  createdByIdx: index('core_archiveresult_created_by_idx').on(table.created_by_id),
  snapshotIdx: index('core_archiveresult_snapshot_idx').on(table.snapshot_id),
  extractorIdx: index('core_archiveresult_extractor_idx').on(table.extractor),
  statusIdx: index('core_archiveresult_status_idx').on(table.status),
  retryAtIdx: index('core_archiveresult_retry_at_idx').on(table.retry_at),
  abidIdx: index('core_archiveresult_abid_idx').on(table.abid),
}));

export const archive_resultsRelations = relations(archive_results, ({ one, many }) => ({
  created_by: one(users, {
    fields: [archive_results.created_by_id],
    references: [users.id],
  }),
  snapshot: one(snapshots, {
    fields: [archive_results.snapshot_id],
    references: [snapshots.id],
  }),
  outlinks: many(outlinks),
}));

// ============================================
// SNAPSHOT TAGS (Junction Table)
// ============================================

export const snapshot_tags = pgTable('core_snapshot_tags', {
  id: integer('id')
    .primaryKey(),

  snapshot_id: uuid('snapshot_id')
    .notNull()
    .references(() => snapshots.id, { onDelete: 'cascade' }),

  tag_id: uuid('tag_id')
    .notNull()
    .references(() => tags.id, { onDelete: 'cascade' }),

}, (table) => ({
  uniqueSnapshotTag: unique().on(table.snapshot_id, table.tag_id),
}));

export const snapshot_tagsRelations = relations(snapshot_tags, ({ one }) => ({
  snapshot: one(snapshots, {
    fields: [snapshot_tags.snapshot_id],
    references: [snapshots.id],
  }),
  tag: one(tags, {
    fields: [snapshot_tags.tag_id],
    references: [tags.id],
  }),
}));

// ============================================
// OUTLINK TABLE
// ============================================

export const outlinks = pgTable('crawls_outlink', {
  // Primary Key
  id: id_field(),

  // Link Data
  src: text('src')
    .notNull(),

  dst: text('dst')
    .notNull(),

  // Foreign Keys
  crawl_id: uuid('crawl_id')
    .notNull()
    .references(() => crawls.id, { onDelete: 'cascade' }),

  via_id: uuid('via_id')
    .references(() => archive_results.id, { onDelete: 'set null' }),

}, (table) => ({
  uniqueSrcDstVia: unique().on(table.src, table.dst, table.via_id),
}));

export const outlinksRelations = relations(outlinks, ({ one }) => ({
  crawl: one(crawls, {
    fields: [outlinks.crawl_id],
    references: [crawls.id],
  }),
  via: one(archive_results, {
    fields: [outlinks.via_id],
    references: [archive_results.id],
  }),
}));
