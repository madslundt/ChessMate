# Chessmate visual specification

Reference: concept.png generated with built-in Image Gen. Primary surface: functional chess game, no marketing wrapper.

Tokens: canvas #f8f9f7, panel #ffffff, ink #182628, muted #637071, line #e5e9e6, pine #204b3d, sage board #8aa18c, pale board #e9ecd9; 12px panels, 7px buttons, 24px desktop gaps. Georgia serif headlines and brand; system sans UI. Sidebar 224px, content flexible board column and 350px coach panel. At <=1050px sidebar contracts; <=760px nav becomes bottom rail and coach follows board. Dark theme uses #151e1b canvas and #202c26 panels with readable high contrast text.

Visible initial copy: Chessmate; Play, Learn, Analyze, Game history, Progress, Settings; A little better, every move.; Your next good move starts with understanding.; New game; Stockfish; Beginner; Guided training; Coach, Moves; Your thinking partner; Play with curiosity.; Take your time. Control the center, develop your pieces, and keep your king safe.; Give me a hint; Compare 3 moves; Hints first. Answers when you ask.; Ask about this position…; You; White; Flip; Explore position; Local & private.

Required extensions using same components: login form, game setup modal, explore status band, candidate rows, feedback, Learn categorized lists and exercise board, history table, progress/topic bars, settings forms. The image is reference only; all controls and board are React. Standard react-chessboard SVG pieces intentionally replace image-generated chess artwork, preserving correct king/queen squares. Board coordinates are inside squares to support mobile. Add explicit computer response control and turn status for requested pause behavior. Both are functional necessities.
