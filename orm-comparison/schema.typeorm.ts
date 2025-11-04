// ArchiveBox Schema - TypeORM
// TypeORM uses TypeScript decorators on classes
// Line count: ~550 lines

import {
  Entity,
  PrimaryColumn,
  Column,
  ManyToOne,
  OneToMany,
  ManyToMany,
  JoinTable,
  JoinColumn,
  Index,
  Unique,
  CreateDateColumn,
  UpdateDateColumn,
  BeforeInsert,
} from 'typeorm';
import { uuidv7 } from 'uuidv7';

// ============================================
// User Entity (Django's default User)
// ============================================
@Entity('auth_user')
@Index('auth_user_username_idx', ['username'])
export class User {
  @PrimaryColumn('uuid')
  id: string;

  @Column({ type: 'varchar', length: 150, unique: true })
  username: string;

  @Column({ type: 'varchar', length: 254 })
  email: string;

  @Column({ type: 'varchar', length: 128 })
  password: string;

  @Column({ type: 'varchar', length: 150 })
  first_name: string;

  @Column({ type: 'varchar', length: 150 })
  last_name: string;

  @Column({ type: 'boolean', default: true })
  is_active: boolean;

  @Column({ type: 'boolean', default: false })
  is_staff: boolean;

  @Column({ type: 'boolean', default: false })
  is_superuser: boolean;

  @CreateDateColumn({ type: 'timestamptz' })
  date_joined: Date;

  @Column({ type: 'timestamptz', nullable: true })
  last_login: Date | null;

  // Relations
  @OneToMany(() => Tag, tag => tag.created_by)
  tags: Tag[];

  @OneToMany(() => KVTag, kvTag => kvTag.created_by)
  kv_tags: KVTag[];

  @OneToMany(() => Seed, seed => seed.created_by)
  seeds: Seed[];

  @OneToMany(() => Crawl, crawl => crawl.created_by)
  crawls: Crawl[];

  @OneToMany(() => CrawlSchedule, schedule => schedule.created_by)
  crawl_schedules: CrawlSchedule[];

  @OneToMany(() => Snapshot, snapshot => snapshot.created_by)
  snapshots: Snapshot[];

  @OneToMany(() => ArchiveResult, result => result.created_by)
  archive_results: ArchiveResult[];

  @BeforeInsert()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// Tag Entity (being phased out)
// ============================================
@Entity('core_tag')
@Index('core_tag_created_at_idx', ['created_at'])
@Index('core_tag_created_by_idx', ['created_by_id'])
@Index('core_tag_abid_idx', ['abid'])
export class Tag {
  @PrimaryColumn('uuid')
  id: string;

  @Column({ type: 'varchar', length: 30, unique: true })
  abid: string;

  @CreateDateColumn({ type: 'timestamptz' })
  created_at: Date;

  @UpdateDateColumn({ type: 'timestamptz' })
  modified_at: Date;

  @Column({ type: 'uuid' })
  created_by_id: string;

  @Column({ type: 'varchar', length: 100, unique: true })
  name: string;

  @Column({ type: 'varchar', length: 100, unique: true })
  slug: string;

  // Relations
  @ManyToOne(() => User, user => user.tags, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'created_by_id' })
  created_by: User;

  @ManyToMany(() => Snapshot, snapshot => snapshot.tags)
  snapshots: Snapshot[];

  @BeforeInsert()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// KVTag Entity (key-value tags)
// ============================================
@Entity('core_kvtags')
@Unique(['obj_id', 'name'])
@Index('core_kvtags_created_at_idx', ['created_at'])
@Index('core_kvtags_obj_type_idx', ['obj_type'])
@Index('core_kvtags_obj_id_idx', ['obj_id'])
export class KVTag {
  @PrimaryColumn('uuid')
  id: string;

  @CreateDateColumn({ type: 'timestamptz' })
  created_at: Date;

  @Column({ type: 'varchar', length: 255 })
  name: string;

  @Column({ type: 'text', nullable: true })
  value: string | null;

  @Column({ type: 'varchar', length: 100 })
  obj_type: string;

  @Column({ type: 'uuid' })
  obj_id: string;

  @Column({ type: 'uuid' })
  created_by_id: string;

  // Relations
  @ManyToOne(() => User, user => user.kv_tags, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'created_by_id' })
  created_by: User;

  @BeforeInsert()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// Seed Entity
// ============================================
@Entity('crawls_seed')
@Unique(['created_by_id', 'uri', 'extractor'])
@Unique(['created_by_id', 'label'])
@Index('crawls_seed_created_at_idx', ['created_at'])
@Index('crawls_seed_created_by_idx', ['created_by_id'])
@Index('crawls_seed_abid_idx', ['abid'])
export class Seed {
  @PrimaryColumn('uuid')
  id: string;

  @Column({ type: 'varchar', length: 30, unique: true })
  abid: string;

  @CreateDateColumn({ type: 'timestamptz' })
  created_at: Date;

  @UpdateDateColumn({ type: 'timestamptz' })
  modified_at: Date;

  @Column({ type: 'uuid' })
  created_by_id: string;

  @Column({ type: 'text' })
  uri: string;

  @Column({ type: 'varchar', length: 32, default: 'auto' })
  extractor: string;

  @Column({ type: 'varchar', length: 255, default: '' })
  tags_str: string;

  @Column({ type: 'varchar', length: 255, default: '' })
  label: string;

  @Column({ type: 'jsonb', default: {} })
  config: object;

  @Column({ type: 'varchar', length: 255, default: '' })
  output_dir: string;

  @Column({ type: 'text', default: '' })
  notes: string;

  @Column({ type: 'int', default: 0 })
  num_uses_failed: number;

  @Column({ type: 'int', default: 0 })
  num_uses_succeeded: number;

  // Relations
  @ManyToOne(() => User, user => user.seeds, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'created_by_id' })
  created_by: User;

  @OneToMany(() => Crawl, crawl => crawl.seed)
  crawls: Crawl[];

  @BeforeInsert()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// CrawlSchedule Entity
// ============================================
@Entity('crawls_crawlschedule')
@Index('crawls_crawlschedule_created_at_idx', ['created_at'])
@Index('crawls_crawlschedule_created_by_idx', ['created_by_id'])
@Index('crawls_crawlschedule_template_idx', ['template_id'])
@Index('crawls_crawlschedule_abid_idx', ['abid'])
export class CrawlSchedule {
  @PrimaryColumn('uuid')
  id: string;

  @Column({ type: 'varchar', length: 30, unique: true })
  abid: string;

  @CreateDateColumn({ type: 'timestamptz' })
  created_at: Date;

  @UpdateDateColumn({ type: 'timestamptz' })
  modified_at: Date;

  @Column({ type: 'uuid' })
  created_by_id: string;

  @Column({ type: 'uuid' })
  template_id: string;

  @Column({ type: 'varchar', length: 64 })
  schedule: string;

  @Column({ type: 'boolean', default: true })
  is_enabled: boolean;

  @Column({ type: 'varchar', length: 64, default: '' })
  label: string;

  @Column({ type: 'text', default: '' })
  notes: string;

  @Column({ type: 'int', default: 0 })
  num_uses_failed: number;

  @Column({ type: 'int', default: 0 })
  num_uses_succeeded: number;

  // Relations
  @ManyToOne(() => User, user => user.crawl_schedules, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'created_by_id' })
  created_by: User;

  @ManyToOne(() => Crawl, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'template_id' })
  template: Crawl;

  @OneToMany(() => Crawl, crawl => crawl.schedule)
  crawls: Crawl[];

  @BeforeInsert()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// Crawl Entity
// ============================================
@Entity('crawls_crawl')
@Index('crawls_crawl_created_at_idx', ['created_at'])
@Index('crawls_crawl_created_by_idx', ['created_by_id'])
@Index('crawls_crawl_seed_idx', ['seed_id'])
@Index('crawls_crawl_schedule_idx', ['schedule_id'])
@Index('crawls_crawl_status_idx', ['status'])
@Index('crawls_crawl_retry_at_idx', ['retry_at'])
@Index('crawls_crawl_abid_idx', ['abid'])
export class Crawl {
  @PrimaryColumn('uuid')
  id: string;

  @Column({ type: 'varchar', length: 30, unique: true })
  abid: string;

  @CreateDateColumn({ type: 'timestamptz' })
  created_at: Date;

  @UpdateDateColumn({ type: 'timestamptz' })
  modified_at: Date;

  @Column({ type: 'uuid' })
  created_by_id: string;

  @Column({ type: 'uuid' })
  seed_id: string;

  @Column({ type: 'text', default: '' })
  urls: string;

  @Column({ type: 'jsonb', default: {} })
  config: object;

  @Column({ type: 'smallint', default: 0 })
  max_depth: number;

  @Column({ type: 'varchar', length: 1024, default: '' })
  tags_str: string;

  @Column({ type: 'uuid', nullable: true })
  persona_id: string | null;

  @Column({ type: 'varchar', length: 64, default: '' })
  label: string;

  @Column({ type: 'text', default: '' })
  notes: string;

  @Column({ type: 'uuid', nullable: true })
  schedule_id: string | null;

  @Column({ type: 'varchar', length: 16, default: 'queued' })
  status: string;

  @Column({ type: 'timestamptz', default: () => 'CURRENT_TIMESTAMP' })
  retry_at: Date;

  @Column({ type: 'varchar', length: 255, default: '' })
  output_dir: string;

  @Column({ type: 'int', default: 0 })
  num_uses_failed: number;

  @Column({ type: 'int', default: 0 })
  num_uses_succeeded: number;

  // Relations
  @ManyToOne(() => User, user => user.crawls, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'created_by_id' })
  created_by: User;

  @ManyToOne(() => Seed, seed => seed.crawls, { onDelete: 'RESTRICT' })
  @JoinColumn({ name: 'seed_id' })
  seed: Seed;

  @ManyToOne(() => CrawlSchedule, schedule => schedule.crawls, { onDelete: 'SET NULL', nullable: true })
  @JoinColumn({ name: 'schedule_id' })
  schedule: CrawlSchedule | null;

  @OneToMany(() => Snapshot, snapshot => snapshot.crawl)
  snapshots: Snapshot[];

  @OneToMany(() => Outlink, outlink => outlink.crawl)
  outlinks: Outlink[];

  @BeforeInsert()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// Snapshot Entity
// ============================================
@Entity('core_snapshot')
@Index('core_snapshot_created_at_idx', ['created_at'])
@Index('core_snapshot_created_by_idx', ['created_by_id'])
@Index('core_snapshot_crawl_idx', ['crawl_id'])
@Index('core_snapshot_url_idx', ['url'])
@Index('core_snapshot_timestamp_idx', ['timestamp'])
@Index('core_snapshot_bookmarked_at_idx', ['bookmarked_at'])
@Index('core_snapshot_downloaded_at_idx', ['downloaded_at'])
@Index('core_snapshot_title_idx', ['title'])
@Index('core_snapshot_status_idx', ['status'])
@Index('core_snapshot_retry_at_idx', ['retry_at'])
@Index('core_snapshot_abid_idx', ['abid'])
export class Snapshot {
  @PrimaryColumn('uuid')
  id: string;

  @Column({ type: 'varchar', length: 30, unique: true })
  abid: string;

  @CreateDateColumn({ type: 'timestamptz' })
  created_at: Date;

  @UpdateDateColumn({ type: 'timestamptz' })
  modified_at: Date;

  @Column({ type: 'uuid' })
  created_by_id: string;

  @Column({ type: 'text', unique: true })
  url: string;

  @Column({ type: 'varchar', length: 32, unique: true })
  timestamp: string;

  @Column({ type: 'timestamptz' })
  bookmarked_at: Date;

  @Column({ type: 'uuid', nullable: true })
  crawl_id: string | null;

  @Column({ type: 'varchar', length: 512, nullable: true })
  title: string | null;

  @Column({ type: 'timestamptz', nullable: true })
  downloaded_at: Date | null;

  @Column({ type: 'timestamptz', default: () => 'CURRENT_TIMESTAMP' })
  retry_at: Date;

  @Column({ type: 'varchar', length: 16, default: 'queued' })
  status: string;

  @Column({ type: 'jsonb', default: {} })
  config: object;

  @Column({ type: 'text', default: '' })
  notes: string;

  @Column({ type: 'varchar', length: 255, nullable: true })
  output_dir: string | null;

  @Column({ type: 'int', default: 0 })
  num_uses_failed: number;

  @Column({ type: 'int', default: 0 })
  num_uses_succeeded: number;

  // Relations
  @ManyToOne(() => User, user => user.snapshots, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'created_by_id' })
  created_by: User;

  @ManyToOne(() => Crawl, crawl => crawl.snapshots, { onDelete: 'CASCADE', nullable: true })
  @JoinColumn({ name: 'crawl_id' })
  crawl: Crawl | null;

  @ManyToMany(() => Tag, tag => tag.snapshots)
  @JoinTable({
    name: 'core_snapshot_tags',
    joinColumn: { name: 'snapshot_id', referencedColumnName: 'id' },
    inverseJoinColumn: { name: 'tag_id', referencedColumnName: 'id' },
  })
  tags: Tag[];

  @OneToMany(() => ArchiveResult, result => result.snapshot)
  archive_results: ArchiveResult[];

  @BeforeInsert()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// ArchiveResult Entity
// ============================================
@Entity('core_archiveresult')
@Index('core_archiveresult_created_at_idx', ['created_at'])
@Index('core_archiveresult_created_by_idx', ['created_by_id'])
@Index('core_archiveresult_snapshot_idx', ['snapshot_id'])
@Index('core_archiveresult_extractor_idx', ['extractor'])
@Index('core_archiveresult_status_idx', ['status'])
@Index('core_archiveresult_retry_at_idx', ['retry_at'])
@Index('core_archiveresult_abid_idx', ['abid'])
export class ArchiveResult {
  @PrimaryColumn('uuid')
  id: string;

  @Column({ type: 'varchar', length: 30, unique: true })
  abid: string;

  @CreateDateColumn({ type: 'timestamptz' })
  created_at: Date;

  @UpdateDateColumn({ type: 'timestamptz' })
  modified_at: Date;

  @Column({ type: 'uuid' })
  created_by_id: string;

  @Column({ type: 'uuid' })
  snapshot_id: string;

  @Column({ type: 'varchar', length: 32 })
  extractor: string;

  @Column({ type: 'varchar', length: 256, nullable: true })
  pwd: string | null;

  @Column({ type: 'jsonb', nullable: true })
  cmd: object | null;

  @Column({ type: 'varchar', length: 128, nullable: true })
  cmd_version: string | null;

  @Column({ type: 'varchar', length: 1024, nullable: true })
  output: string | null;

  @Column({ type: 'timestamptz', nullable: true })
  start_ts: Date | null;

  @Column({ type: 'timestamptz', nullable: true })
  end_ts: Date | null;

  @Column({ type: 'varchar', length: 16, default: 'queued' })
  status: string;

  @Column({ type: 'timestamptz', default: () => 'CURRENT_TIMESTAMP' })
  retry_at: Date;

  @Column({ type: 'text', default: '' })
  notes: string;

  @Column({ type: 'varchar', length: 256, nullable: true })
  output_dir: string | null;

  @Column({ type: 'uuid', nullable: true })
  iface_id: string | null;

  @Column({ type: 'int', default: 0 })
  num_uses_failed: number;

  @Column({ type: 'int', default: 0 })
  num_uses_succeeded: number;

  // Relations
  @ManyToOne(() => User, user => user.archive_results, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'created_by_id' })
  created_by: User;

  @ManyToOne(() => Snapshot, snapshot => snapshot.archive_results, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'snapshot_id' })
  snapshot: Snapshot;

  @OneToMany(() => Outlink, outlink => outlink.via)
  outlinks: Outlink[];

  @BeforeInsert()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}

// ============================================
// Outlink Entity
// ============================================
@Entity('crawls_outlink')
@Unique(['src', 'dst', 'via_id'])
export class Outlink {
  @PrimaryColumn('uuid')
  id: string;

  @Column({ type: 'text' })
  src: string;

  @Column({ type: 'text' })
  dst: string;

  @Column({ type: 'uuid' })
  crawl_id: string;

  @Column({ type: 'uuid', nullable: true })
  via_id: string | null;

  // Relations
  @ManyToOne(() => Crawl, crawl => crawl.outlinks, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'crawl_id' })
  crawl: Crawl;

  @ManyToOne(() => ArchiveResult, result => result.outlinks, { onDelete: 'SET NULL', nullable: true })
  @JoinColumn({ name: 'via_id' })
  via: ArchiveResult | null;

  @BeforeInsert()
  generateId() {
    if (!this.id) {
      this.id = uuidv7();
    }
  }
}
