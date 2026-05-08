# cc-plugins

A small marketplace of [Claude Code](https://docs.claude.com/en/docs/claude-code) plugins.

## Plugins

| Plugin | What it does |
|--------|-------------|
| [statusline](plugins/statusline/) | Two-line statusline showing dir, git branch, model, effort, context %, session cost, and time since the last response. Bonus: Salesforce org indicator if `.sf/config.json` is present. |

## Install a plugin

Add the marketplace once, then install whichever plugins you want:

```
/plugin marketplace add jf4nathan/cc-plugins
/plugin install statusline@cc-plugins
```

Each plugin's README has its own setup instructions (e.g. for `statusline`, run `/statusline:setup` after install).

## Update plugins

```
/plugin marketplace update cc-plugins
```

Some plugins (like `statusline`) ship a `/<plugin>:update` skill that re-syncs any files they install into `~/.claude/` while preserving your customizations. See the plugin's README.

## Repo layout

```
.
├── .claude-plugin/marketplace.json   # marketplace manifest
└── plugins/
    └── statusline/
        ├── .claude-plugin/plugin.json
        ├── README.md
        ├── hooks/hooks.json
        ├── scripts/
        └── skills/
            ├── setup/SKILL.md
            └── update/SKILL.md
```

## Contributing

Issues and PRs welcome. Each plugin lives in its own subdirectory under `plugins/` and is registered in the marketplace via `.claude-plugin/marketplace.json`.

## License

MIT
