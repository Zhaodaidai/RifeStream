import vapoursynth as vs


if not hasattr(vs.core, "bs"):
    raise vs.Error("BestSource plugin is not loaded")

vs.core.std.BlankClip(width=16, height=16, length=1).set_output()
