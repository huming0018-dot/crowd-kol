# Explicit same-ACK material recompute regression

Source is the adjacent formal multiplatform code, never an output candidate. From that directory run:

```sh
CROWD_MATERIAL_TEST_ROOT=/absolute/private/saved-workbench PYTHONPATH=. /existing/toolbox-python -B -m unittest test_material_recompute
node test_material_recompute_ui.mjs
```

The explicit input root must contain the existing pinned `data-products/material-auto-runtime.json` and a ready saved Pro task29 ACK context/group. Missing input is an error, never a skip or PASS. The existing Python environment must provide the pinned toolbox; no dependency install, SDK, token or saved private input is bundled. Tests read those inputs and use temporary directories for all writes/Jobs/KnowledgeStore releases; no source/model/cloud call. Two engineering fixture releases exercise the existing review/release engine, not production human approval. Existing immutable output four formats stay readable during a separate recompute; explicit local Consumer selection does not change knowledge pin or issued cloud publication. Runtime adoption requires both Owner runtime and separately pinned knowledge service bundle; source integration alone does not activate this feature.
