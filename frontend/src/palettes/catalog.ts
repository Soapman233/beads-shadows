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
  source: string; licenseStatus: string; status: string; colors: Color[];
};
export async function loadDatabasePalette(versionId: string) {
  const id = 'db:' + versionId;
  if (!isDatabasePalette(id)) throw Error('色卡版本无效');
  const response = await fetch('/api/palettes/' + versionId, { cache: 'no-store' });
  if (!response.ok) throw Error('数据库色卡暂不可用');
  const data: DatabaseVersion = await response.json();
  const colors = data.colors.map(({ code, hex }) => ({ code, hex }));
  DATABASE_PALETTES.set(id, {
    id, colors, name: data.brand + ' / ' + data.series + ' · ' + data.version,
    info: {
      brand: data.brand, series: data.series + ' ' + data.sizeMm + 'mm', version: data.version,
      source: data.source, license: data.licenseStatus, note: '数据库色卡 · ' + (data.status === 'published' ? '已发布' : '已退役'),
    },
    available: data.status === 'published', retrievedAt: '', declaredCount: colors.length,
  });
}

export async function loadPublishedPalettes() {
  const result = await fetch('/api/palettes', { cache: 'no-store' });
  if (!result.ok) return;
  const versions: { id: string }[] = await result.json();
  for (const [id, palette] of DATABASE_PALETTES) {
    if (!versions.some(v => 'db:' + v.id === id)) DATABASE_PALETTES.set(id, { ...palette, available: false });
  }
  await Promise.all(versions.map(v => loadDatabasePalette(v.id)));
}
