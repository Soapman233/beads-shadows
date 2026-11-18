export type BuildInfo = { appId: string; buildId: string; builtAt: string };
declare const __BEADS_BUILD_INFO__: BuildInfo;
export const BUILD_INFO: Readonly<BuildInfo> = Object.freeze(__BEADS_BUILD_INFO__);
