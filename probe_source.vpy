import vapoursynth as vs


source_path = globals().get("input")
if not source_path:
    raise vs.Error("Missing input argument")
if not hasattr(vs.core, "bs"):
    raise vs.Error("BestSource plugin is not loaded")

vs.core.bs.VideoSource(
    source=source_path,
    variableformat=0,
    cachemode=1,
    showprogress=False,
).set_output()
