# Architecture diagrams (PlantUML)

| File | Type | Shows |
|---|---|---|
| [01-layers.puml](01-layers.puml) | component | the layers (Discord-facing, Services, Core, Storage) and who talks to whom |
| [02-module-dependencies.puml](02-module-dependencies.puml) | component | which module imports which; Core never imports Discord |
| [03-state-model.puml](03-state-model.puml) | class | `GameState` and every dataclass inside it |
| [04-enums.puml](04-enums.puml) | class | the enums (phases, life states, chat kinds, timings, priorities...) |
| [05-roles-and-abilities.puml](05-roles-and-abilities.puml) | class | `RoleBase` / `Role` / `Modifier`, `Ability` / `Param`, command cogs, registries |
| [06-resolution-classes.puml](06-resolution-classes.puml) | class | `Resolution`, `Visit`, `Attack`, `Protection`, `Report`, hook registries |
| [07-resolution-pipeline.puml](07-resolution-pipeline.puml) | activity | the steps of `Resolution.run()` |
| [08-services.puml](08-services.puml) | class | `GameService`, `GameWorker`, delivery, channels, audit, database |
| [09-database.puml](09-database.puml) | entity | the five SQLite tables |
| [10-seq-player-command.puml](10-seq-player-command.puml) | sequence | a player command from slash command to Discord |
| [11-seq-transition.puml](11-seq-transition.puml) | sequence | night lock preview and morning application |
| [12-seq-dusk-and-decision.puml](12-seq-dusk-and-decision.puml) | sequence | dusk, the lynch tally and a Mayor tiebreak decision |
| [13-seq-realtime.puml](13-seq-realtime.puml) | sequence | eavesdrops, yes/no questions, telepath messages |
| [14-state-game-phases.puml](14-state-game-phases.puml) | state | game phases and transitions |
| [15-state-action-and-life.puml](15-state-action-and-life.puml) | state | action statuses and player life states |
| [16-channel-access.puml](16-channel-access.puml) | activity | how `player_access` decides channel permissions |
| [17-effects.puml](17-effects.puml) | class | effect types and where they're delivered |
| [18-seq-startup.puml](18-seq-startup.puml) | sequence | startup and crash recovery |

## Rendering

The class, component and state diagrams use `!pragma layout smetana`, PlantUML's built-in layout engine. That
means you only need Java, not Graphviz.

- **VS Code:** install the "PlantUML" extension (jebbs.plantuml) and press `Alt+D` on a `.puml` file.
- **Command line:** download `plantuml.jar` from <https://plantuml.com/download>, then run:

  ```bash
  java -jar plantuml.jar -tsvg Docs/diagrams/*.puml
  ```
