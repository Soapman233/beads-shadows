import { shallowReactive } from 'vue';
import type { Color, PaletteInfo } from '../engine';
import { MARD_COLORS } from './mard';
import { PIXEL_MARD_COLORS } from './pixel-mard';
import { PIXEL_PERLER_COLORS } from './pixel-perler';
import { PIXEL_HAMA_COLORS } from './pixel-hama';
import { PIXEL_ARTKAL_COLORS } from './pixel-artkal';

export type PaletteDefinition = {
  id: string;
  name: string;
  colors: Color[];
  info: PaletteInfo;
  retrievedAt: string;
  declaredCount: number;
  available: boolean;
  cached?: boolean;
};
const retrievedAt = '2026-11-17';
const page = (brand: string) => `https://www.pixel-beads.com/zh/${brand}-bead-color-chart`;
const rights = '来源未提供开放数据许可；不适用本项目MIT授权';
function reference(id: string, name: string, brand: string, series: string, declaredCount: number, colors: Color[]): PaletteDefinition {
  return {
    id, name, colors, retrievedAt, declaredCount, available: colors.length > 0,
    info: {
      brand, series, version: `pixel-beads 页面参考 ${retrievedAt}`,
      source: page(brand.toLowerCase()), license: rights,
      note: '网站屏幕参考，非厂家实测认证。特殊材质不能由单一HEX完整表达；备料请核对实物。',
    },
  };
}
export const PALETTES: PaletteDefinition[] = [
  reference('pixel-perler', 'Perler', 'Perler', '页面录入范围', 124, PIXEL_PERLER_COLORS),
  reference('pixel-hama-midi', 'Hama / Midi', 'Hama', 'Midi', 91, PIXEL_HAMA_COLORS),
  reference('pixel-artkal-s', 'Artkal / S', 'Artkal', 'S 5mm', 225, PIXEL_ARTKAL_COLORS),
  reference('pixel-mard', 'MARD', 'MARD', '标准221 + 扩展70（含特殊材质）', 291, PIXEL_MARD_COLORS),
  {
    id: 'legacy-mard220', name: 'MARD 220 · 旧版兼容', colors: MARD_COLORS,
    retrievedAt: '2026-11-15', declaredCount: 220, available: true,
    info: {
      brand: 'MARD', series: '经典221编号体系中的当前220色子集（暂不纳入H1）',
      version: 'beadcolors社区参考 2026-11-15',
      source: 'https://github.com/maxcleme/beadcolors/blob/master/raw/mard.csv',
      license: 'MIT · Copyright (c) 2020 maxcleme',
      note: '社区屏幕参考色，非厂家认证；H1暂不纳入当前子集，其材质属性待核实。备料与色差需核对实物。',
    },
  },
];
export const DEFAULT_PALETTE_ID = 'pixel-mard';
export const DATABASE_PALETTES = shallowReactive(new Map<string, PaletteDefinition>());
export function getPalette(id: string): PaletteDefinition | undefined {
  return DATABASE_PALETTES.get(id) ?? PALETTES.find((p) => p.id === id);
}

export function isDatabasePalette(id: unknown): id is string {
  return typeof id === 'string' && /^db:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
}

type DatabaseVersion = {
  id: string; brand: string; series: string; sizeMm: number; version: string;
  source: string; licenseStatus: string; status: 'published' | 'retired'; colors: Color[];
};
const cacheKey = 'beads.public-palettes.v1';
const cacheLimit = 16;
const versions = new Map<string, DatabaseVersion>();
const publicRequest = { cache: 'no-store', credentials: 'omit', redirect: 'error' } as const;

const shortText = (value: unknown, max: number): value is string =>
  typeof value === 'string' && value.length > 0 && value.length <= max;

function normalizeVersion(value: unknown): DatabaseVersion | undefined {
  if (!value || typeof value !== 'object') return;
  const { id, brand, series, sizeMm, version, source, licenseStatus, status, colors } = value as Partial<DatabaseVersion>;
  if (typeof id !== 'string' || !isDatabasePalette('db:' + id) ||
      !shortText(brand, 60) || !shortText(series, 60) || !shortText(version, 80) ||
      !shortText(source, 800) || !/^https?:\/\//i.test(source) || !shortText(licenseStatus, 30) ||
      typeof sizeMm !== 'number' || !Number.isFinite(sizeMm) || sizeMm <= 0 || sizeMm > 50 ||
      (status !== 'published' && status !== 'retired') || !Array.isArray(colors) ||
      !colors.length || colors.length > 512) return;
  const safeColors: Color[] = [];
  const codes = new Set<string>();
  for (const color of colors) {
    if (!color || typeof color.code !== 'string' || typeof color.hex !== 'string' ||
        !/^[A-Za-z0-9_.-]{1,32}$/.test(color.code) || !/^#[0-9a-f]{6}$/i.test(color.hex) ||
        ['__proto__', 'prototype', 'constructor'].includes(color.code) || codes.has(color.code)) return;
    codes.add(color.code);
    safeColors.push({ code: color.code, hex: color.hex });
  }
  return { id, brand, series, sizeMm, version, source, licenseStatus, status, colors: safeColors };
}

function rememberVersion(data: DatabaseVersion, cached: boolean) {
  const id = 'db:' + data.id;
  versions.delete(data.id);
  versions.set(data.id, data);
  DATABASE_PALETTES.set(id, {
    id, colors: data.colors, name: data.brand + ' / ' + data.series + ' · ' + data.version,
    info: {
      brand: data.brand, series: data.series + ' ' + data.sizeMm + 'mm', version: data.version,
      source: data.source, license: data.licenseStatus, note: '数据库色卡 · ' + (data.status === 'published' ? '已发布' : '已退役'),
    },
    available: data.status === 'published', cached, retrievedAt: '', declaredCount: data.colors.length,
  });
}

function savePublicPaletteCache() {
  try { localStorage.setItem(cacheKey, JSON.stringify([...versions.values()].slice(-cacheLimit))); }
  catch { /* The editor remains usable when persistent browser storage is unavailable. */ }
}

export function restorePublicPaletteCache() {
  try {
    const stored = localStorage.getItem(cacheKey);
    if (!stored || stored.length > 600_000) return;
    const data: unknown = JSON.parse(stored);
    if (!Array.isArray(data)) return;
    for (const item of data.slice(-cacheLimit)) {
      const version = normalizeVersion(item);
      if (version && !versions.has(version.id)) rememberVersion(version, true);
    }
  } catch { /* Invalid or disabled browser storage does not block the editor. */ }
}

async function fetchDatabasePalette(versionId: string) {
  if (!isDatabasePalette('db:' + versionId)) throw Error('色卡版本无效');
  const response = await fetch('/api/palettes/' + versionId, publicRequest);
  if (!response.ok) throw Error('数据库色卡暂不可用');
  const version = normalizeVersion(await response.json());
  if (!version || version.id !== versionId) throw Error('数据库色卡数据无效');
  rememberVersion(version, false);
}

export async function loadDatabasePalette(versionId: string) {
  await fetchDatabasePalette(versionId);
  savePublicPaletteCache();
}

export async function loadPublishedPalettes() {
  const known = [...versions.values()];
  const result = await fetch('/api/palettes', publicRequest);
  if (!result.ok) return;
  const published: unknown = await result.json();
  if (!Array.isArray(published) || published.some(v => v?.status !== 'published' ||
      typeof v.id !== 'string' || !isDatabasePalette('db:' + v.id))) return;
  const active = new Set<string>(published.map(v => v.id));
  for (const version of known) {
    if (version.status === 'published' && !active.has(version.id) && versions.get(version.id) === version) {
      rememberVersion({ ...version, status: 'retired' }, false);
    }
  }
  await Promise.allSettled([...active].map(fetchDatabasePalette));
  savePublicPaletteCache();
}
