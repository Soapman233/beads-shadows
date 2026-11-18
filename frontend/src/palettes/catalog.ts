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
export function getPalette(id: string): PaletteDefinition | undefined {
  return PALETTES.find((p) => p.id === id);
}
