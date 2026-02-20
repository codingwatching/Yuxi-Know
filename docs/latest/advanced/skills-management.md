# Skills 管理

Skills 管理模块用于集中维护可供 Agent 只读引用的技能包。  
本期采用“文件系统存内容，数据库存索引”模式：

1. 技能目录存储在 `/app/saves/skills`（本地 `save_dir/skills`）。
2. 技能元数据（slug/name/description/dir_path）存储在 `skills` 表。
3. Agent 配置通过 `context.skills` 选择技能，运行时挂载到 `/skills` 且只读。

## 权限与入口

1. 系统设置中新增 `Skills 管理` 页签（仅 `superadmin` 可见）。
2. `admin` 仅可调用列表接口（用于 Agent 配置选择 skills）。
3. `user` 无 skills 管理权限。

## 导入规范（ZIP）

1. 单包单技能，且必须包含一个 `SKILL.md`。
2. `SKILL.md` 必须包含 frontmatter，且 `name`、`description` 必填。
3. `name` 需满足 slug 规则：小写字母/数字/短横线。
4. 导入时执行路径安全校验，拒绝绝对路径与 `..` 路径穿越。
5. slug 冲突时自动追加 `-v2/-v3...`，并自动改写 `SKILL.md` 中 `name` 为最终 slug。
6. 导入采用临时目录 + 原子替换，避免半成品落盘。

## 在线管理能力

1. Skills 列表：来自数据库，避免全量目录扫描。
2. 目录树：按原生目录结构展示。
3. 文件级 CRUD：支持新建文件/目录、编辑文本文件、删除文件/目录。
4. 文件编辑仅允许文本类型（如 md/py/js/ts/json/yaml/toml/txt 等）。
5. `SKILL.md` 保存后会重新解析，并同步更新数据库中的 `name/description`。
6. 支持导出单个 skill 为 ZIP。
7. 删除 skill 时会同时删除目录与数据库记录（硬删除）。

## Agent 运行时行为

1. `context.skills` 用于配置技能 slug 列表。
2. 运行时仅暴露选中 skills 到 `/skills/<slug>/...`。
3. `/skills` 路径只读，不允许写入、编辑、上传。
4. 变更在下一次对话请求生效。
