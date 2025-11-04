// ArchiveBox Schema - MikroORM
// MikroORM uses TypeScript decorators similar to TypeORM but with different patterns
// Line count: ~570 lines

import {
  Entity,
  PrimaryKey,
  Property,
  ManyToOne,
  OneToMany,
  ManyToMany,
  Collection,
  Index,
  Unique,
  BeforeCreate,
} from '@mikro-orm/core';
import { uuidv7 } from 'uuidv7';

// ============================================
// User Entity (Django's default User)
// ============================================
@Entity({ tableName: 'auth_user' })
@Index({ properties: ['username'] })
export class User {
  @PrimaryKey({ type: 'uuid' })
  id!: string;

  @Property({ type: 'string', length: 150, unique: true })
  username!: string;

  @Property({ type: 'string', length: 254 })
  email!: string;

  @Property({ type: 'string', length: 128 })
  password!: string;

  @Property({ type: 'string', length: 150 })
  first_name!: string;

  @Property({ type: 'string', length: 150 })
  last_name!: string;

  @Property({ type: 'boolean', default: true })
  is_active = true;

  @Property({ type: 'boolean', default: false })
  is_staff = false;

  @Property({ type: 'boolean', default: false })
  is_superuser = false;

  @Property({ type: 'timestamptz', onCreate: () => new Date() })
  date_joined!: Date;

  @Property({ type: 'timestamptz', nullable: true })
  last_login?: Date;

  // Relations
  @OneToMany(() => Tag, tag => tag.created_by)
  tags = new Collection<Tag>(this);

  @OneToMany(() => KVTag, kvTag => kvTag.created_by)
  kv_tags = new Collection<KVTag>(this);

  @OneToMany(() => Seed, seed => seed.created_by)
  seeds = new Collection<Seed>(this);

  @OneToMany(() => Crawl, crawl => crawl.created_by)
  crawls = new Collection<Crawl>(this);

  @OneToMany(() => CrawlSchedule, schedule => schedule.created_by)
  crawl_schedules = new Collection<CrawlSchedule>(this);

  @OneToMany(() => Snapshot, snapshot => snapshot.created_by)
  snapshots = new Collection<Snapshot>(this);

  @OneToMany(() => ArchiveResult, result => result.created_by)
  archive_results = new Collection<ArchiveResult>(this);

  @BeforeCreate()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// Tag Entity (being phased out)
// ============================================
@Entity({ tableName: 'core_tag' })
@Index({ properties: ['created_at'] })
@Index({ properties: ['created_by_id'] })
@Index({ properties: ['abid'] })
export class Tag {
  @PrimaryKey({ type: 'uuid' })
  id!: string;

  @Property({ type: 'string', length: 30, unique: true })
  abid!: string;

  @Property({ type: 'timestamptz', onCreate: () => new Date() })
  created_at!: Date;

  @Property({ type: 'timestamptz', onUpdate: () => new Date() })
  modified_at!: Date;

  @Property({ type: 'uuid', persist: false })
  created_by_id!: string;

  @Property({ type: 'string', length: 100, unique: true })
  name!: string;

  @Property({ type: 'string', length: 100, unique: true })
  slug!: string;

  // Relations
  @ManyToOne(() => User, { onDelete: 'cascade', fieldName: 'created_by_id' })
  created_by!: User;

  @ManyToMany(() => Snapshot, snapshot => snapshot.tags)
  snapshots = new Collection<Snapshot>(this);

  @BeforeCreate()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// KVTag Entity (key-value tags)
// ============================================
@Entity({ tableName: 'core_kvtags' })
@Unique({ properties: ['obj_id', 'name'] })
@Index({ properties: ['created_at'] })
@Index({ properties: ['obj_type'] })
@Index({ properties: ['obj_id'] })
export class KVTag {
  @PrimaryKey({ type: 'uuid' })
  id!: string;

  @Property({ type: 'timestamptz', onCreate: () => new Date() })
  created_at!: Date;

  @Property({ type: 'string', length: 255 })
  name!: string;

  @Property({ type: 'text', nullable: true })
  value?: string;

  @Property({ type: 'string', length: 100 })
  obj_type!: string;

  @Property({ type: 'uuid' })
  obj_id!: string;

  @Property({ type: 'uuid', persist: false })
  created_by_id!: string;

  // Relations
  @ManyToOne(() => User, { onDelete: 'cascade', fieldName: 'created_by_id' })
  created_by!: User;

  @BeforeCreate()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// Seed Entity
// ============================================
@Entity({ tableName: 'crawls_seed' })
@Unique({ properties: ['created_by_id', 'uri', 'extractor'] })
@Unique({ properties: ['created_by_id', 'label'] })
@Index({ properties: ['created_at'] })
@Index({ properties: ['created_by_id'] })
@Index({ properties: ['abid'] })
export class Seed {
  @PrimaryKey({ type: 'uuid' })
  id!: string;

  @Property({ type: 'string', length: 30, unique: true })
  abid!: string;

  @Property({ type: 'timestamptz', onCreate: () => new Date() })
  created_at!: Date;

  @Property({ type: 'timestamptz', onUpdate: () => new Date() })
  modified_at!: Date;

  @Property({ type: 'uuid', persist: false })
  created_by_id!: string;

  @Property({ type: 'text' })
  uri!: string;

  @Property({ type: 'string', length: 32, default: 'auto' })
  extractor = 'auto';

  @Property({ type: 'string', length: 255, default: '' })
  tags_str = '';

  @Property({ type: 'string', length: 255, default: '' })
  label = '';

  @Property({ type: 'json', default: {} })
  config: object = {};

  @Property({ type: 'string', length: 255, default: '' })
  output_dir = '';

  @Property({ type: 'text', default: '' })
  notes = '';

  @Property({ type: 'integer', default: 0 })
  num_uses_failed = 0;

  @Property({ type: 'integer', default: 0 })
  num_uses_succeeded = 0;

  // Relations
  @ManyToOne(() => User, { onDelete: 'cascade', fieldName: 'created_by_id' })
  created_by!: User;

  @OneToMany(() => Crawl, crawl => crawl.seed)
  crawls = new Collection<Crawl>(this);

  @BeforeCreate()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// CrawlSchedule Entity
// ============================================
@Entity({ tableName: 'crawls_crawlschedule' })
@Index({ properties: ['created_at'] })
@Index({ properties: ['created_by_id'] })
@Index({ properties: ['template_id'] })
@Index({ properties: ['abid'] })
export class CrawlSchedule {
  @PrimaryKey({ type: 'uuid' })
  id!: string;

  @Property({ type: 'string', length: 30, unique: true })
  abid!: string;

  @Property({ type: 'timestamptz', onCreate: () => new Date() })
  created_at!: Date;

  @Property({ type: 'timestamptz', onUpdate: () => new Date() })
  modified_at!: Date;

  @Property({ type: 'uuid', persist: false })
  created_by_id!: string;

  @Property({ type: 'uuid', persist: false })
  template_id!: string;

  @Property({ type: 'string', length: 64 })
  schedule!: string;

  @Property({ type: 'boolean', default: true })
  is_enabled = true;

  @Property({ type: 'string', length: 64, default: '' })
  label = '';

  @Property({ type: 'text', default: '' })
  notes = '';

  @Property({ type: 'integer', default: 0 })
  num_uses_failed = 0;

  @Property({ type: 'integer', default: 0 })
  num_uses_succeeded = 0;

  // Relations
  @ManyToOne(() => User, { onDelete: 'cascade', fieldName: 'created_by_id' })
  created_by!: User;

  @ManyToOne(() => Crawl, { onDelete: 'cascade', fieldName: 'template_id' })
  template!: Crawl;

  @OneToMany(() => Crawl, crawl => crawl.schedule)
  crawls = new Collection<Crawl>(this);

  @BeforeCreate()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// Crawl Entity
// ============================================
@Entity({ tableName: 'crawls_crawl' })
@Index({ properties: ['created_at'] })
@Index({ properties: ['created_by_id'] })
@Index({ properties: ['seed_id'] })
@Index({ properties: ['schedule_id'] })
@Index({ properties: ['status'] })
@Index({ properties: ['retry_at'] })
@Index({ properties: ['abid'] })
export class Crawl {
  @PrimaryKey({ type: 'uuid' })
  id!: string;

  @Property({ type: 'string', length: 30, unique: true })
  abid!: string;

  @Property({ type: 'timestamptz', onCreate: () => new Date() })
  created_at!: Date;

  @Property({ type: 'timestamptz', onUpdate: () => new Date() })
  modified_at!: Date;

  @Property({ type: 'uuid', persist: false })
  created_by_id!: string;

  @Property({ type: 'uuid', persist: false })
  seed_id!: string;

  @Property({ type: 'text', default: '' })
  urls = '';

  @Property({ type: 'json', default: {} })
  config: object = {};

  @Property({ type: 'smallint', default: 0 })
  max_depth = 0;

  @Property({ type: 'string', length: 1024, default: '' })
  tags_str = '';

  @Property({ type: 'uuid', nullable: true })
  persona_id?: string;

  @Property({ type: 'string', length: 64, default: '' })
  label = '';

  @Property({ type: 'text', default: '' })
  notes = '';

  @Property({ type: 'uuid', nullable: true, persist: false })
  schedule_id?: string;

  @Property({ type: 'string', length: 16, default: 'queued' })
  status = 'queued';

  @Property({ type: 'timestamptz', onCreate: () => new Date() })
  retry_at!: Date;

  @Property({ type: 'string', length: 255, default: '' })
  output_dir = '';

  @Property({ type: 'integer', default: 0 })
  num_uses_failed = 0;

  @Property({ type: 'integer', default: 0 })
  num_uses_succeeded = 0;

  // Relations
  @ManyToOne(() => User, { onDelete: 'cascade', fieldName: 'created_by_id' })
  created_by!: User;

  @ManyToOne(() => Seed, { onDelete: 'restrict', fieldName: 'seed_id' })
  seed!: Seed;

  @ManyToOne(() => CrawlSchedule, { onDelete: 'set null', nullable: true, fieldName: 'schedule_id' })
  schedule?: CrawlSchedule;

  @OneToMany(() => Snapshot, snapshot => snapshot.crawl)
  snapshots = new Collection<Snapshot>(this);

  @OneToMany(() => Outlink, outlink => outlink.crawl)
  outlinks = new Collection<Outlink>(this);

  @BeforeCreate()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// Snapshot Entity
// ============================================
@Entity({ tableName: 'core_snapshot' })
@Index({ properties: ['created_at'] })
@Index({ properties: ['created_by_id'] })
@Index({ properties: ['crawl_id'] })
@Index({ properties: ['url'] })
@Index({ properties: ['timestamp'] })
@Index({ properties: ['bookmarked_at'] })
@Index({ properties: ['downloaded_at'] })
@Index({ properties: ['title'] })
@Index({ properties: ['status'] })
@Index({ properties: ['retry_at'] })
@Index({ properties: ['abid'] })
export class Snapshot {
  @PrimaryKey({ type: 'uuid' })
  id!: string;

  @Property({ type: 'string', length: 30, unique: true })
  abid!: string;

  @Property({ type: 'timestamptz', onCreate: () => new Date() })
  created_at!: Date;

  @Property({ type: 'timestamptz', onUpdate: () => new Date() })
  modified_at!: Date;

  @Property({ type: 'uuid', persist: false })
  created_by_id!: string;

  @Property({ type: 'text', unique: true })
  url!: string;

  @Property({ type: 'string', length: 32, unique: true })
  timestamp!: string;

  @Property({ type: 'timestamptz' })
  bookmarked_at!: Date;

  @Property({ type: 'uuid', nullable: true, persist: false })
  crawl_id?: string;

  @Property({ type: 'string', length: 512, nullable: true })
  title?: string;

  @Property({ type: 'timestamptz', nullable: true })
  downloaded_at?: Date;

  @Property({ type: 'timestamptz', onCreate: () => new Date() })
  retry_at!: Date;

  @Property({ type: 'string', length: 16, default: 'queued' })
  status = 'queued';

  @Property({ type: 'json', default: {} })
  config: object = {};

  @Property({ type: 'text', default: '' })
  notes = '';

  @Property({ type: 'string', length: 255, nullable: true })
  output_dir?: string;

  @Property({ type: 'integer', default: 0 })
  num_uses_failed = 0;

  @Property({ type: 'integer', default: 0 })
  num_uses_succeeded = 0;

  // Relations
  @ManyToOne(() => User, { onDelete: 'cascade', fieldName: 'created_by_id' })
  created_by!: User;

  @ManyToOne(() => Crawl, { onDelete: 'cascade', nullable: true, fieldName: 'crawl_id' })
  crawl?: Crawl;

  @ManyToMany(() => Tag, tag => tag.snapshots, { owner: true, pivotTable: 'core_snapshot_tags' })
  tags = new Collection<Tag>(this);

  @OneToMany(() => ArchiveResult, result => result.snapshot)
  archive_results = new Collection<ArchiveResult>(this);

  @BeforeCreate()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// ArchiveResult Entity
// ============================================
@Entity({ tableName: 'core_archiveresult' })
@Index({ properties: ['created_at'] })
@Index({ properties: ['created_by_id'] })
@Index({ properties: ['snapshot_id'] })
@Index({ properties: ['extractor'] })
@Index({ properties: ['status'] })
@Index({ properties: ['retry_at'] })
@Index({ properties: ['abid'] })
export class ArchiveResult {
  @PrimaryKey({ type: 'uuid' })
  id!: string;

  @Property({ type: 'string', length: 30, unique: true })
  abid!: string;

  @Property({ type: 'timestamptz', onCreate: () => new Date() })
  created_at!: Date;

  @Property({ type: 'timestamptz', onUpdate: () => new Date() })
  modified_at!: Date;

  @Property({ type: 'uuid', persist: false })
  created_by_id!: string;

  @Property({ type: 'uuid', persist: false })
  snapshot_id!: string;

  @Property({ type: 'string', length: 32 })
  extractor!: string;

  @Property({ type: 'string', length: 256, nullable: true })
  pwd?: string;

  @Property({ type: 'json', nullable: true })
  cmd?: object;

  @Property({ type: 'string', length: 128, nullable: true })
  cmd_version?: string;

  @Property({ type: 'string', length: 1024, nullable: true })
  output?: string;

  @Property({ type: 'timestamptz', nullable: true })
  start_ts?: Date;

  @Property({ type: 'timestamptz', nullable: true })
  end_ts?: Date;

  @Property({ type: 'string', length: 16, default: 'queued' })
  status = 'queued';

  @Property({ type: 'timestamptz', onCreate: () => new Date() })
  retry_at!: Date;

  @Property({ type: 'text', default: '' })
  notes = '';

  @Property({ type: 'string', length: 256, nullable: true })
  output_dir?: string;

  @Property({ type: 'uuid', nullable: true })
  iface_id?: string;

  @Property({ type: 'integer', default: 0 })
  num_uses_failed = 0;

  @Property({ type: 'integer', default: 0 })
  num_uses_succeeded = 0;

  // Relations
  @ManyToOne(() => User, { onDelete: 'cascade', fieldName: 'created_by_id' })
  created_by!: User;

  @ManyToOne(() => Snapshot, { onDelete: 'cascade', fieldName: 'snapshot_id' })
  snapshot!: Snapshot;

  @OneToMany(() => Outlink, outlink => outlink.via)
  outlinks = new Collection<Outlink>(this);

  @BeforeCreate()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// Outlink Entity
// ============================================
@Entity({ tableName: 'crawls_outlink' })
@Unique({ properties: ['src', 'dst', 'via_id'] })
export class Outlink {
  @PrimaryKey({ type: 'uuid' })
  id!: string;

  @Property({ type: 'text' })
  src!: string;

  @Property({ type: 'text' })
  dst!: string;

  @Property({ type: 'uuid', persist: false })
  crawl_id!: string;

  @Property({ type: 'uuid', nullable: true, persist: false })
  via_id?: string;

  // Relations
  @ManyToOne(() => Crawl, { onDelete: 'cascade', fieldName: 'crawl_id' })
  crawl!: Crawl;

  @ManyToOne(() => ArchiveResult, { onDelete: 'set null', nullable: true, fieldName: 'via_id' })
  via?: ArchiveResult;

  @BeforeCreate()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}
