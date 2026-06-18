"""SIGame Statistics Analyzer + SiQ Viewer.

Vendored into SI-HYX as the «SiQuester» tab. The video preview was ported from
mpv to QtMultimedia (see :mod:`siquester.widgets_players`), so there is no longer
a native ``libmpv-2.dll`` to locate — ffmpeg (used for LUFS/info) is found via
the host app's ``bin`` directory, which the SI-HYX wrapper puts on PATH.
"""
