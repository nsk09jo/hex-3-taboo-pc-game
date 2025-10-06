# Hex 3‑Taboo PC Adaptation Plan

## 1. Concept and game design

**Summary**: Hex 3‑Taboo is a two‑player abstract strategy game played on a hexagonal grid. Players take turns placing stones of their color on any empty hex. The goal is to create a straight line of four or more connected stones (4‑in‑a‑row) to win while avoiding creating an isolated three‑stone line (exactly three in a row). A 3‑in‑a‑row line that is part of a longer line (length ≥4) does not trigger the loss penalty; wins override losses. These rules encourage players to build longer connections while carefully managing intermediate patterns.

### Board geometry

- The board is a regular hexagonal tiling truncated to a finite radius *R*. A radius of 4 (61 cells) provides a balanced play space; radius 5 (91 cells) is an option for longer games.
- The board has three principal axes at 60° intervals. Lines are defined along these axes; only perfectly straight lines count towards win/loss conditions—bent lines do not.

### Turn sequence

1. Players alternate turns; no passes are allowed.
2. **Placement**: On their turn a player must either:
   - **Place** one stone of their color on any empty cell.
   - **Neutralize (once per game, for the second player only)**: The second player may once per game, instead of placing a stone, neutralize the opponent’s last placed stone. The target stone remains on the board but becomes neutral (belongs to neither player). Neutralizing concludes the turn and cannot be used to negate a win already recorded.
3. **Evaluation order** (at the end of each turn):
  - **Victory**: If the just‑placed player (or the player whose neutralization ended the turn) has at least one straight line of four or more consecutive stones of their color, they win immediately.
   - **Loss**: If they have no winning line but have one or more straight lines that are exactly three stones long (neither shorter nor longer), they lose immediately.
   - If neither condition is met, play continues. If the board fills without a win/loss, the game is a draw.
4. **Equal outcomes**: If a turn simultaneously produces a winning line and an exactly three‑stone line, the win takes precedence.

### Additional match rules

- **Time control**: For online play or tournaments, configurable timers (e.g., 10 min per player with a 10 second increment) ensure fairness.
- **Scoring series**: In match play the first player can be alternated or balanced via series; track wins, losses, draws and second‑player advantages (the neutralization ability only applies to the second player in each game).

## 2. Digital adaptation goals

Designing a PC version requires translating the tactile board into an intuitive, responsive digital experience. Modern digital board games provide automated rule enforcement, tutorials, and online multiplayer. Our goals for the PC adaptation are:

1. **Ease of learning**  
   - Integrate an interactive tutorial that demonstrates placement, neutralization, and the win/lose conditions. Digital board games benefit from built‑in lessons and visual aids.
   - Provide tooltips and optional hints that highlight potential 3‑in‑a‑row risks and 4‑in‑a‑row opportunities.  
   - Offer rule summaries and glossary accessible at any time.

2. **Automated setup and rule enforcement**  
   - The software automatically provides an empty board at the start, enforces alternating turns, and prohibits invalid moves.  
   - Win/loss conditions are checked programmatically at the end of each turn, eliminating disputes over scoring.

3. **User interface**  
   - **Board rendering**: Implement a clean 2D top‑down view of the hex grid with subtle shading and coordinates. When a player hovers over a cell, highlight potential placement.  
   - **Line highlighting**: When a line of two or more consecutive stones is created, highlight it briefly; highlight winning lines distinctly and mark exactly three‑stone lines with warning colors or rings.  
   - **Neutralization indicator**: Show a “neutralize” button for the second player until it is used; on click, highlight only the opponent’s most recent stone as eligible.
   - **Accessibility**: Provide color‑blind friendly palettes and adjustable size/zoom.

4. **Modes of play**  
   - **Local hot‑seat**: Two players share a computer.  
   - **Versus AI**: Provide AI opponents with adjustable difficulty; AI may use heuristic evaluation functions (connectivity, threat blocking).  
   - **Online multiplayer**: Support networked games via a lobby; players can invite friends or play ranked matches.  
   - **Practice mode**: Allow single‑player sandboxing with undo/redo and analysis tools.

5. **Quality of life**  
   - **Undo / redo**: In practice and local modes, allow players to undo the last move (except when a win or loss has been declared).  
   - **Save / load**: Save games to disk and reload them later.  
   - **Statistics and analysis**: Track win/loss ratios, average turn count, and highlight common patterns to help players improve.

6. **Platform and distribution**  
   - Target Windows, macOS, and Linux; consider engines such as Unity (C#), Godot (GDScript/C#), or a web‑based implementation (TypeScript/React) packaged as a desktop app via Electron.  
   - Distribute via Steam or Itch.io; incorporate achievements and leaderboards for engagement.

## 3. Technical architecture

- **Core game engine**  
  - Maintain the board state in a two‑dimensional axial coordinate array.  
  - Implement algorithms to detect straight lines along three axes quickly after each move; scan outward from the new stone to count consecutive stones and determine whether a line is exactly three or four or more.  
  - Encapsulate rules (turn order, neutralization, win/loss detection) in a single authoritative game state class.
  - Provide a history stack to enable undo/redo.

- **User interface layer**  
  - Use a scene graph or component library to render the hex grid. Each cell is clickable and can display states: empty, occupied by player 1, occupied by player 2, highlighted.  
  - Compose UI panels for player info, timers, move history, and settings.  
  - Implement animations (e.g., fade‑in stone placement, line glow) with a tweening library to enhance feedback.

- **Networking (for online play)**  
  - Implement a client‑server architecture using WebSockets or a real‑time game server library.  
  - Handle matchmaking, game state synchronization, and latency compensation.  
  - Persist match results in a server database for leaderboards.

- **Artificial intelligence**  
  - Start with simple heuristics: maximize own potential connections, block opponent’s threats, use the neutralization ability strategically.
  - Optionally implement Monte Carlo Tree Search (MCTS) or minimax with alpha‑beta pruning for stronger AI.

- **Tutorial scripting**  
  - Design a sequence of scripted steps demonstrating placement, losing with three in a row, winning with four, and using the neutralization ability.
  - Use overlay text, arrows, and interactive prompts to guide players through each mechanic.

## 4. Development roadmap

1. **Pre‑production (Weeks 1‑2)**  
   - Finalize game design and digital adaptation requirements.  
   - Choose engine/technology stack.  
   - Create visual mock‑ups of the board and UI.

2. **Core engine implementation (Weeks 3‑4)**  
   - Implement board data structure and turn logic.  
   - Implement win/loss detection and the neutralization mechanic.
   - Build a simple command‑line prototype for testing rules.

3. **User interface (Weeks 5‑7)**  
   - Render the hex grid and implement input handling.  
   - Create HUD elements (player indicators, timers, remove button).  
   - Add visual feedback for line formation, wins, losses, and invalid moves.

4. **Single‑player and AI (Weeks 8‑9)**  
   - Integrate AI opponents with basic heuristics.  
   - Add undo/redo and game save functionality.  
   - Implement local hot‑seat mode.

5. **Tutorial and onboarding (Week 10)**  
   - Script the interactive tutorial using engine’s UI system.  
   - Integrate rulebook/FAQ accessible in game.

6. **Online multiplayer (Weeks 11‑14)**  
   - Develop matchmaking and network synchronization.  
   - Implement user accounts and rating system if applicable.  
   - Conduct closed beta testing to gather feedback on latency and fairness.

7. **Polish and launch (Weeks 15‑16)**  
   - Refine UI aesthetics, animations, and audio.  
   - Implement achievements, leaderboards, and analytics.  
   - Optimize performance and fix bugs.  
   - Prepare marketing materials and launch on distribution platforms.

## 5. Future enhancements

- **Variant rules**: Option to adjust board size, change the neutralization mechanic to other balancing schemes (e.g., swap or double move), or introduce additional stones with special effects.
- **Cross‑platform support**: Extend to mobile (iOS/Android) and browser with shared codebase.
- **Spectator mode and replay system**: Allow others to watch games live or review completed games with move-by-move playback.
- **Community content**: Enable users to create custom boards, themes, and rule sets.

## Running the prototype

Install Python 3.8+ with Tkinter. To play from the command line:

```bash
python hex3_taboo.py --mode cli
```

To launch the GUI version instead (requires Tkinter):

```bash
python hex3_taboo.py --mode gui
```

You can adjust the board radius in either mode with `--radius` (default 4).
