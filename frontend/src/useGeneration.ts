import { ref, onBeforeUnmount } from "vue";
import type { Pattern } from "./engine";
import { validateConstraints } from "./constraints";
import { getPalette } from "./palettes/catalog";
export class GenerationCancelledError extends Error {
  constructor() {
    super("已取消");
    this.name = "GenerationCancelledError";
  }
}
export function isGenerationCancelled(error: unknown): boolean {
  return error instanceof GenerationCancelledError;
}
export function useGeneration() {
  const busy = ref(false);
  let worker: Worker | undefined,
    serial = 0,
    rejectPending: ((e: Error) => void) | undefined;
  function cancel() {
    serial++;
    worker?.terminate();
    worker = undefined;
    busy.value = false;
    const reject = rejectPending;
    rejectPending = undefined;
    reject?.(new GenerationCancelledError());
  }
  function run(
    pixels: Uint8ClampedArray,
    mask: Uint8Array,
    width: number,
    height: number,
    custom = false,
    n = 64,
    k = 16,
    constraints?: import("./constraints").Constraints,
    paletteId = "legacy-mard220",
  ) {
    cancel();
    const id = ++serial;
    busy.value = true;
    return new Promise<{ label: string; pattern: Pattern }[]>(
      (resolve, reject) => {
        rejectPending = reject;
        let current: Worker | undefined;
        const finish = () => {
          current?.terminate();
          if (id === serial) {
            worker = undefined;
            busy.value = false;
            rejectPending = undefined;
          }
        };
        const fail = (error: Error) => {
          if (id !== serial) return;
          finish();
          reject(error);
        };
        try {
          const palette = getPalette(paletteId);
          if (!palette?.available) throw Error("所选色卡当前不可用");
          // Rebuild plain arrays at the transport boundary: Vue Proxy values
          // are valid inputs but cannot be structured-cloned by postMessage.
          const plainConstraints = constraints
            ? validateConstraints(constraints, k, palette.colors)
            : undefined;
          current = new Worker(
            new URL("./generation.worker.ts", import.meta.url),
            { type: "module" },
          );
          worker = current;
          current.onmessage = ({ data: v }) => {
            if (id !== serial) return;
            if (!v || v.id !== id) {
              fail(Error("生成结果无效，请重试"));
              return;
            }
            finish();
            v.error ? reject(Error(v.error)) : resolve(v.result);
          };
          current.onerror = () => fail(Error("生成失败，请重试"));
          current.onmessageerror = () =>
            fail(Error("生成结果读取失败，请重试"));
          const p = pixels.slice(),
            m = mask.slice();
          current.postMessage(
            {
              id,
              pixels: p.buffer,
              mask: m.buffer,
              width,
              height,
              custom,
              n,
              k,
              constraints: plainConstraints,
              paletteId,
            },
            [p.buffer, m.buffer],
          );
        } catch (error) {
          fail(error instanceof Error ? error : Error("生成启动失败，请重试"));
        }
      },
    );
  }
  onBeforeUnmount(cancel);
  return { busy, run, cancel };
}
