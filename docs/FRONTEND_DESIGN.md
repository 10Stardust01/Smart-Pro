# SMART-PRO frontend design

The workspace uses warm white surfaces on a cool grey canvas, charcoal text
and a restrained teal accent. The typography and use of space draw on the
Hazzel education presentation. Operational content, tables and controls use
SMART-PRO's own layouts and assets.

- Define shared color, spacing, radius and elevation in the tokens at the top
  of `frontend/styles.css`. Use the system font stack for local and hosted views.
- Use the application rail for role navigation. Set `aria-current="page"` on
  the active destination. Keep context and return paths in the established
  URL and history state.
- Use one prominent action in a section when possible. Use secondary buttons
  for supporting actions and quiet buttons for contextual links.
- Use a panel for a section and a project card for a repeated record. Show
  authoritative statuses in text. Treat color as a supporting cue.
- Keep form labels visible. Preserve native keyboard behavior for buttons,
  dialogs and disclosures. Use the shared focus outline and status messages.
- Put wide tables in a labeled, keyboard-focusable scrolling region.
  At small widths, stack form columns and keep page content within the viewport.
- Keep artwork and dependencies local and lightweight. Respect reduced motion.

## Institutional redesign

Hazzel / Clear Education informs more than colors: editorial headings, whitespace,
warm white panels, quiet charcoal type and restrained teal linework. Landing views
prioritize the next real task, relevant metrics and academic records rather than
feature inventories. Faculty reference data is retained, but its provenance is
shown only on demand within assignment or records contexts.

The Django API, role authorization, native ES module runtime and academic records
remain unchanged in this phase. Manual Playwright synthetic-browser tests guard
responsive rendering and role-specific navigation.
