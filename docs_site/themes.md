# Themes

## Shipped themes

| Name | Description |
| ---- | ----------- |
| `teengirl_notebook` | Warm cream diary — default. |
| `colorblind_safe`   | Wong 2011 palette for color-vision-deficiency users. |
| `legacy_glass`      | Glassmorphism dark, matches the pre-rename Pharos look. |
| `dark_studio`       | Graphite-dark with cyan accents. |
| `high_contrast`     | WCAG-AAA-passing text contrast. |
| `pastel_soft`       | Cream + lilac, sparse washi. |

## Notebook decor knobs (Sprint 9)

Every theme YAML can declare optional `washi_tape`, `page_lining`, and
`edge_stroke` sections:

```yaml
washi_tape:
  variant: minimal | floral | off
  density: none | low | medium | high

page_lining:
  style: off | rule | dot_grid | isometric
  density: none | low | medium | high

edge_stroke:
  width: 0.5 - 2.0
  style: crisp | brushed | pencil | none
```

## User themes

Drop `*.yaml` files into `~/.pharos/themes/`. `ThemeCatalog` scans that
directory in addition to the shipped set; user themes with the same
`name:` win.

## Extension-contributed themes

Plugins register theme paths through
`ExtensionRegistry.register_theme(path)`. Calling
`registry.sync_user_themes()` copies them into `~/.pharos/themes/` so
the catalog picks them up.
