# Qoder Adapter

This machine currently exposes Qoder skills under:

```text
C:\Users\Liang\.qoder\skills
```

I did not find a `C:\Users\Liang\.qoderwork` plugin workspace. For now, Qoder can reuse the EasyGEE and bundled GeoMaster skills by linking or copying:

```text
C:\Users\Liang\plugins\easygee\skills\easygee
C:\Users\Liang\plugins\easygee\skills\geomaster
C:\Users\Liang\plugins\easygee\skills\gee-growth-diary
```

If Qoder later exposes a plugin manifest format, keep this plugin as the canonical source and add a thin adapter here instead of maintaining a separate EasyGEE copy.
