# Atlas commits

- Before every commit for the atlas, run `python scripts/bump-map-version.py`.
- Include `map/data/map-version.json`, `map/index.html`, and `map/renewables.html` in that same commit.
- Run `python scripts/bump-map-version.py --check` before publishing.
- The current displayed version must match in the map title, compact filter header, build metadata, debug output, and renewable inventory.
- Preserve historical snapshots, source URLs, data-schema versions and third-party library versions when updating the atlas version.
- Automated update workflows must also bump and stage the version before publishing each generated commit. Do this after synchronizing with main, then amend the generated commit so concurrent cache jobs inherit the latest version.
