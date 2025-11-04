// ArchiveBox Schema - Drizzle ORM
// Drizzle uses TypeScript schema definitions with a chainable API
// Line count: ~340 lines

import { pgTable, uuid, varchar, text, boolean, timestamp, smallint, integer, json, unique, index } from 'drizzle-orm/pg-core';
import { relations } from 'drizzle-orm';
import { uuidv7 } from 'uuidv7';

// Helper for UUIDv7 default
const uuidv7Default = () => uuidv7();

// ============================================
// User Model (Django's default User)
// ============================================
export const users = pgTable('auth_user', {
  id: uuid('id').primaryKey().$defaultFn(uuidv7Default),
  username: varchar('username', { length: 150 }).unique().notNull(),
  email: varchar('email', { length: 254 }).notNull(),
  password: varchar('password', { length: 128 }).notNull(),
  first_name: varchar('first_name', { length: 150 }).notNull(),
  last_name: varchar('last_name', { length: 150 }).notNull(),
  is_active: boolean('is_active').default(true).notNull(),
  is_staff: boolean('is_staff').default(false).notNull(),
  is_superuser: boolean('is_superuser').default(false).notNull(),
  date_joined: timestamp('date_joined', { withTimezone: true }).defaultNow().notNull(),
  last_login: timestamp('last_login', { withTimezone: true }),
}, (table) => ({
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
// Old-style Tag Model (being phased out)
// ============================================
export const tags = pgTable('core_tag', {
  id: uuid('id').primaryKey().$defaultFn(uuidv7Default),
  abid: varchar('abid', { length: 30 }).unique().notNull(),
  created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  modified_at: timestamp('modified_at', { withTimezone: true }).defaultNow().notNull(),
  created_by_id: uuid('created_by_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  name: varchar('name', { length: 100 }).unique().notNull(),
  slug: varchar('slug', { length: 100 }).unique().notNull(),
}, (table) => ({
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
// New-style KVTag Model (key-value tags)
// ============================================
export const kv_tags = pgTable('core_kvtags', {
  id: uuid('id').primaryKey().$defaultFn(uuidv7Default),
  created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  name: varchar('name', { length: 255 }).notNull(),
  value: text('value'),
  obj_type: varchar('obj_type', { length: 100 }).notNull(),
  obj_id: uuid('obj_id').notNull(),
}, (table) => ({
  uniqueObjTag: unique().on(table.obj_id, table.name),
  createdAtIdx: index('core_kvtags_created_at_idx').on(table.created_at),
  objTypeIdx: index('core_kvtags_obj_type_idx').on(table.obj_type),
  objIdIdx: index('core_kvtags_obj_id_idx').on(table.obj_id),
}));

export const kv_tagsRelations = relations(kv_tags, ({ one }) => ({
  // Generic foreign key - handled in application logic
}));

// ============================================
// Seed Model (URL source)
// ============================================
export const seeds = pgTable('crawls_seed', {
  id: uuid('id').primaryKey().$defaultFn(uuidv7Default),
  abid: varchar('abid', { length: 30 }).unique().notNull(),
  created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  modified_at: timestamp('modified_at', { withTimezone: true }).defaultNow().notNull(),
  created_by_id: uuid('created_by_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  uri: text('uri').notNull(),
  extractor: varchar('extractor', { length: 32 }).default('auto').notNull(),
  tags_str: varchar('tags_str', { length: 255 }).default('').notNull(),
  label: varchar('label', { length: 255 }).default('').notNull(),
  config: json('config').default({}).notNull(),
  output_dir: varchar('output_dir', { length: 255 }).default('').notNull(),
  notes: text('notes').default('').notNull(),
  num_uses_failed: integer('num_uses_failed').default(0).notNull(),
  num_uses_succeeded: integer('num_uses_succeeded').default(0).notNull(),
}, (table) => ({
  uniqueUserUriExtractor: unique().on(table.created_by_id, table.uri, table.extractor),
  uniqueUserLabel: unique().on(table.created_by_id, table.label),
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
// CrawlSchedule Model
// ============================================
export const crawl_schedules = pgTable('crawls_crawlschedule', {
  id: uuid('id').primaryKey().$defaultFn(uuidv7Default),
  abid: varchar('abid', { length: 30 }).unique().notNull(),
  created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  modified_at: timestamp('modified_at', { withTimezone: true }).defaultNow().notNull(),
  created_by_id: uuid('created_by_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  template_id: uuid('template_id').notNull().references(() => crawls.id, { onDelete: 'cascade' }),
  schedule: varchar('schedule', { length: 64 }).notNull(),
  is_enabled: boolean('is_enabled').default(true).notNull(),
  label: varchar('label', { length: 64 }).default('').notNull(),
  notes: text('notes').default('').notNull(),
  num_uses_failed: integer('num_uses_failed').default(0).notNull(),
  num_uses_succeeded: integer('num_uses_succeeded').default(0).notNull(),
}, (table) => ({
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
// Crawl Model (archiving session)
// ============================================
export const crawls = pgTable('crawls_crawl', {
  id: uuid('id').primaryKey().$defaultFn(uuidv7Default),
  abid: varchar('abid', { length: 30 }).unique().notNull(),
  created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  modified_at: timestamp('modified_at', { withTimezone: true }).defaultNow().notNull(),
  created_by_id: uuid('created_by_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  seed_id: uuid('seed_id').notNull().references(() => seeds.id, { onDelete: 'restrict' }),
  urls: text('urls').default('').notNull(),
  config: json('config').default({}).notNull(),
  max_depth: smallint('max_depth').default(0).notNull(),
  tags_str: varchar('tags_str', { length: 1024 }).default('').notNull(),
  persona_id: uuid('persona_id'),
  label: varchar('label', { length: 64 }).default('').notNull(),
  notes: text('notes').default('').notNull(),
  schedule_id: uuid('schedule_id').references(() => crawl_schedules.id, { onDelete: 'set null' }),
  status: varchar('status', { length: 16 }).default('queued').notNull(),
  retry_at: timestamp('retry_at', { withTimezone: true }).defaultNow().notNull(),
  output_dir: varchar('output_dir', { length: 255 }).default('').notNull(),
  num_uses_failed: integer('num_uses_failed').default(0).notNull(),
  num_uses_succeeded: integer('num_uses_succeeded').default(0).notNull(),
}, (table) => ({
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
// Snapshot Model (archived URL)
// ============================================
export const snapshots = pgTable('core_snapshot', {
  id: uuid('id').primaryKey().$defaultFn(uuidv7Default),
  abid: varchar('abid', { length: 30 }).unique().notNull(),
  created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  modified_at: timestamp('modified_at', { withTimezone: true }).defaultNow().notNull(),
  created_by_id: uuid('created_by_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  url: text('url').unique().notNull(),
  timestamp: varchar('timestamp', { length: 32 }).unique().notNull(),
  bookmarked_at: timestamp('bookmarked_at', { withTimezone: true }).notNull(),
  crawl_id: uuid('crawl_id').references(() => crawls.id, { onDelete: 'cascade' }),
  title: varchar('title', { length: 512 }),
  downloaded_at: timestamp('downloaded_at', { withTimezone: true }),
  retry_at: timestamp('retry_at', { withTimezone: true }).defaultNow().notNull(),
  status: varchar('status', { length: 16 }).default('queued').notNull(),
  config: json('config').default({}).notNull(),
  notes: text('notes').default('').notNull(),
  output_dir: varchar('output_dir', { length: 255 }),
  num_uses_failed: integer('num_uses_failed').default(0).notNull(),
  num_uses_succeeded: integer('num_uses_succeeded').default(0).notNull(),
}, (table) => ({
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
// ArchiveResult Model (extraction result)
// ============================================
export const archive_results = pgTable('core_archiveresult', {
  id: uuid('id').primaryKey().$defaultFn(uuidv7Default),
  abid: varchar('abid', { length: 30 }).unique().notNull(),
  created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  modified_at: timestamp('modified_at', { withTimezone: true }).defaultNow().notNull(),
  created_by_id: uuid('created_by_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  snapshot_id: uuid('snapshot_id').notNull().references(() => snapshots.id, { onDelete: 'cascade' }),
  extractor: varchar('extractor', { length: 32 }).notNull(),
  pwd: varchar('pwd', { length: 256 }),
  cmd: json('cmd'),
  cmd_version: varchar('cmd_version', { length: 128 }),
  output: varchar('output', { length: 1024 }),
  start_ts: timestamp('start_ts', { withTimezone: true }),
  end_ts: timestamp('end_ts', { withTimezone: true }),
  status: varchar('status', { length: 16 }).default('queued').notNull(),
  retry_at: timestamp('retry_at', { withTimezone: true }).defaultNow().notNull(),
  notes: text('notes').default('').notNull(),
  output_dir: varchar('output_dir', { length: 256 }),
  iface_id: uuid('iface_id'),
  num_uses_failed: integer('num_uses_failed').default(0).notNull(),
  num_uses_succeeded: integer('num_uses_succeeded').default(0).notNull(),
}, (table) => ({
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
// SnapshotTag Junction Table
// ============================================
export const snapshot_tags = pgTable('core_snapshot_tags', {
  id: integer('id').primaryKey(),
  snapshot_id: uuid('snapshot_id').notNull().references(() => snapshots.id, { onDelete: 'cascade' }),
  tag_id: uuid('tag_id').notNull().references(() => tags.id, { onDelete: 'cascade' }),
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
// Outlink Model (link found on a page)
// ============================================
export const outlinks = pgTable('crawls_outlink', {
  id: uuid('id').primaryKey().$defaultFn(uuidv7Default),
  src: text('src').notNull(),
  dst: text('dst').notNull(),
  crawl_id: uuid('crawl_id').notNull().references(() => crawls.id, { onDelete: 'cascade' }),
  via_id: uuid('via_id').references(() => archive_results.id, { onDelete: 'set null' }),
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
