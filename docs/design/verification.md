# Visual and interaction verification

Date: 20 October 2026.

The working [concept](concept.png) was generated with built-in Image Gen and copied into the repository. Its brief called for a calm Scandinavian chess club: warm near-white canvas, white panels, pine actions, sage chessboard, serif headings, a left navigation rail, a large board, and a focused coach panel. All product controls, text, and chess pieces are implemented as interactive React UI; the concept image is not used as the interface.

The final [desktop render](desktop-initial.png), [tablet render](tablet-initial.png), and [mobile render](mobile-initial.png) come from the production build and real authenticated API interactions. The [in-app browser proof](iab-verified.png) shows an actual saved e4 move, Stockfish grading, a paused computer reply, and correctly grounded coaching about White while Black is to move.

## Method

- Opened and operated the application in Codex's in-app browser first. Verified account creation, game setup, legal e4, actual engine feedback, paused computer response, and a coach question. No browser fallback was needed.
- Repeated the full acceptance flow in Playwright Chromium: desktop 1488×1058, iPad Mini emulation, and iPhone 13 emulation. The concept is 1487×1058; the desktop verification viewport differs by one pixel in width. Full-page captures include secondary controls below the viewport.
- Inspected both the concept and the final production screenshot with `view_image` in the same final QA pass. Also inspected tablet/mobile renders and the in-app browser capture.
- Nine production browser scenarios passed. They cover both colors, keyboard/touch move selection, engine response and feedback, exploration isolation/commit, top-three candidates, hints, chat and saved conversation, exercises/progress, history/resume, underpromotion/import/export, independent languages, dark preferences, and repertoire practice.
- The production service worker separately passed first-visit JS/CSS precaching and an offline interface reload. Private API responses are excluded from its cache. Gameplay and analysis still require the server.

## Comparison and repair ledger

| Point | Concept evidence | Final render evidence and resolution |
| --- | --- | --- |
| Composition | Left navigation, central board, right coach; board is the focal point | Desktop preserves the rail and two-panel composition. A 264px rail and 410px coach keep the board and header aligned. Tablet portrait stacks the coach below a usable full-size board. |
| Typography | Serif headline and coach heading; restrained sans controls | Georgia headings and explicit UI type sizes preserve the hierarchy. Fixed an oversized coach title that wrapped unnecessarily and adjusted the headline width. |
| Palette | Near-white canvas, white panels, deep green actions, sage/light chess squares | Explicit tokens retain these colors. No photo overlays, glow, or gradient effects were introduced. Dark mode is a separate user-selected theme. |
| Copy | Main headline, subtitle, six nav entries, Coach/Moves, hints and candidate actions | Core initial copy and order match. Functional additions are listed below; there are no added marketing claims or decorative eyebrow labels. |
| Icons | Play triangle, book, chart, clock, trophy, settings, flip and exploration controls | Corrected early home/target/sliders substitutions to the intended play/trophy/settings/flip metaphors. Shared Lucide components use a consistent stroke and sizing. |
| Container and spacing | Airy white panels, subtle borders, modest radii, minimal nested framing | Shared panels/buttons/tokens preserve this treatment. Coaching feedback and hypothetical state receive purposeful semantic treatments. |
| Actual chess art | Recognizable black/white pieces on a square board | Standard library SVG pieces replace image-generated artwork and preserve the correct king/queen arrangement. No raster board or fake controls are shipped. |
| Accessibility | Readable, simple controls | Fixed missing accessible dialog names, supplied field/control labels, retained keyboard square selection, and checked promotion and game controls. |
| Responsive behavior | Board remains central, compact chrome | Mobile has bottom navigation and the coach follows the board. iPad portrait uses a larger board and stacked coach rather than a cramped desktop split. All three browser profiles assert no horizontal overflow. |

## Copy diff and intentional functional differences

The core initial headline, subtitle, navigation, coach welcome, and hint/candidate labels were preserved. The implementation adds required turn status, practice difficulty, autosave, computer response pause, undo, PGN/FEN, account/sign-out, promotion, error/loading, and exploration controls. These are product requirements from the implementation brief. The board's coordinates sit inside its squares to retain touch space. The guided style is configured in Settings rather than an invented dropdown in the player row. Standard chess pieces correct the image concept's inaccurate king/queen placement.

Visual fidelity was checked against the working concept across layout, typography, palette, icons, copy, spacing, and responsive behavior. The intentional differences above make the real chess workflows usable; no blocking visual mismatch remains in the verified layouts. Emulation does not establish real iOS Safari or hardware compatibility; those remain device checks for deployment.
