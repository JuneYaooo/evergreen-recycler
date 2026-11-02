# 对标与参考逻辑：常青回收排期 + 赢家检测（2026-11-02 复核扩充）

本文件把本项目的每条判断逻辑对照到外部资料：对标产品怎么做、开源实现的真实参数、
方法论出处，以及平台规则的当前真实情况。

- 首轮调研：2026-09-19（v0.1.0，见文末「v0.1.0 首轮结论」）。
- 本轮复核：**2026-11-02**（v0.3.0），用网页搜索、产品帮助文档、GitHub 源码和官方/媒体
  报道交叉核对。每条结论后注明来源，检索日期均为 2026-11-02，另有标注的除外。
- 引用版权归原作者所有，仅作设计参考；产品规则随时可能调整，以官方当前文档为准。
- **可信度标注**：【官方】产品/平台自己的文档或源码；【媒体】新闻报道转述官方规则；
  【第三方】营销博客、经验文章，没有官方出处，只当作参考区间。

## 1. 对标清单与对比表

### 1.1 常青回收 / 重发排期工具

| 方案 | 选帖方式 | 冷却/间隔 | 次数上限 | 时效过滤 | 变体 | 来源 |
| --- | --- | --- | --- | --- | --- | --- |
| CoSchedule ReQueue | 人工把消息放进 ReQueue 组；Intelligent 组自动填日历空档 | 组级频率设置 | 有「发送上限」，达到后自动归档【官方】 | 无 | 无 | [Manage ReQueue Groups](https://coschedule.com/support/social-media/requeue/manage-requeue-groups-2)、[Get started](https://coschedule.com/support/social-media/requeue/get-started-with-requeue) |
| SmarterQueue Evergreen | 人工分类入队，发完回到队尾 | 「最短回收时间」，没到就顺延【官方】；FAQ 写同文本 24h 内不重发、常青队列每周最多重复 2 次 | 可按轮数或日期过期【官方】 | 无 | 无 | [How recycling works](https://help.smarterqueue.com/article/190-how-does-evergreen-post-recycling-work)、[What's new](https://get-help.smarterqueue.com/article/608-evergreen-recycling-whats-new) |
| Revive Old Posts（WordPress 插件） | 全站文章按分类/标签过滤 | 两次分享的最小间隔（小时） | 可选「循环分享」 | **最小帖龄**（示例 30 天）、最大帖龄（Pro）【官方】 | 无 | [Revive Old Post 文档](https://docs.revive.social/article/380-revive-old-post-documentation) |
| SocialBu Recycling | 建议先取近 3-6 个月互动率最高的 10-15 条；新帖先观察 1-2 周 | 平台建议 4-12 周 | 可设 2/3/4/5 次或无限【第三方博客，厂商自写】 | **跳过绑定日期/节日/活动的帖子**；问「6 个月后还成立吗」 | 同文或轻改 | [Social media post recycling](https://socialbu.com/blog/social-media-post-recycling) |
| UniLink Social Planner | 人工选 | Instagram/TikTok 45-90 天、LinkedIn 约 60 天；短间隔+同文案容易被判重复，建议 ≥45 天 | — | — | 至少 2-3 个文案变体轮换 | [Auto-recycle](https://unil.ink/blog/social-planner-auto-recycle)【厂商博客】 |
| OpenTweet Evergreen | 人工加入，建议用高表现帖 | 全局冷却期 + 单帖覆盖；按「上次发布日期 + 冷却」轮转 | 显示回收次数，没有硬上限 | — | 原帖不改，发克隆 | [Evergreen Queue](https://opentweet.io/help/evergreen-queue)【官方】 |
| TryPost（开源，功能提案） | 人工标记 + 高表现优先 | 单帖冷却（示例 45 天） | 单帖最多 N 轮（示例 6 轮），之后自动退役 | 可设生效日期窗口 | 每平台一个变体 | [GitHub discussion #143](https://github.com/orgs/trypostit/discussions/143) |
| Postiz（开源，≈40.7k★） | 人工 | 重复周期选项只有 1/2/3/4/5/6 天、1 周、2 周、1 个月【源码】 | — | — | — | [repeat.component.tsx](https://github.com/gitroomhq/postiz-app/blob/main/apps/frontend/src/components/launches/repeat.component.tsx)（star 数 2026-11-02 用 GitHub API 查得） |
| social-auto-upload（开源，≈16k★） | 不选帖，只做上传自动化 | — | — | — | — | [dreammis/social-auto-upload](https://github.com/dreammis/social-auto-upload) |
| social-calendar-builder（Agent Skill，Apache-2.0） | 「从自己导出数据里挑表现最好的」作回收候选，没有给阈值 | 「设置轮转间隔」，没有给数值 | — | **每次回收前重核日期、价格、说法** | — | [aaron-marketing-skills](https://github.com/aaron-he-zhu/aaron-marketing-skills/tree/HEAD/social/craft/social-calendar-builder) |
| **本项目 v0.3.0** | **自动**：基线中位数 ≥3x 且 ≥P75，可选滚动基线 | 同帖距上次发布（**含首发**）≥60 天；7 天滚动窗口 ≤3 条 | `--max-recycles`（默认不限） | 标题时效词提示（只提示不剔除） | Agent 按帖写 1-3 个变体方向 | 本仓库 |

### 1.2 「赢家 / outlier」检测工具（选帖口径的直接对标）

| 工具 | 口径 | 基线 | 阈值分档 | 来源 |
| --- | --- | --- | --- | --- |
| vidIQ Outliers | 视频播放 ÷ 频道「同一时间段」的平均播放【官方】 | 同频道、相近时期 | <2x 黑 / 2-5x 蓝 / 5-10x 紫 / >10x 红 | [vidIQ help: Outliers](https://support.vidiq.com/en/articles/9660010-outliers) |
| Vamos Outlier Score | 对比创作者**自己的中位数**，不和平台比；**创作者 ≥10 条帖子才显示分数**【官方】 | 自身中位数 | 周报把 ≥2x 中位数算 outlier | [The outlier score](https://intercom.help/getvamos/en/articles/16934858-the-outlier-score) |
| OutlierKit | 播放 ÷ 近期上传的平均 | 近期上传 | 2x 值得注意；**3x+ 是显著 outlier**，建议重点研究 3-10x；20x+ 多半是外部因素，难复制 | [Outlier scores](https://outlierkit.com/resources/outlier-scores/)【厂商】 |
| Overseer 基准报告 | **同帖龄比较**：T 时刻播放 ÷ 同类视频在 T 时刻播放的中位数；基线**排除自身**；默认用中位数（单个爆款会拉高均值）；用「当前阶段」而不是全生命周期；样本 5 条探索 / 10-19 中等 / **20-30 高置信** | 同频道、同格式、同帖龄、近期 | 3-4.99x strong outlier；≥20x 先审基线 | [YouTube outlier benchmark report](https://www.overseeros.com/blog/youtube-outlier-benchmark-report)【厂商】 |
| 1of10 | 按频道「典型播放」评分，公开页没说是均值还是中位数、用哪个窗口 | 未公开 | 10x 示例 | [1of10 homepage outliers](https://1of10.com/features/homepage-outliers) |
| 千瓜 / 新红等国内数据平台 | 公开检索里**没有找到**「爆文 / 低粉爆文」的官方阈值；行业文章只有「爆文率 10%-20%」这种投放要求 | — | — | [人人都是产品经理相关文章](https://www.woshipm.com/share/5902052.html)【第三方】 |

### 1.3 方法论与权威资料

| 资料 | 要点 | 对本项目的影响 |
| --- | --- | --- |
| [NIST/SEMATECH e-Handbook §1.3.5.17 Detection of Outliers](https://www.itl.nist.gov/div898/handbook/eda/section3/eda35h.htm) | 修正 Z 分数 Mᵢ = 0.6745(xᵢ − 中位数)/MAD，\|Mᵢ\| > 3.5 标为潜在离群点（Iglewicz & Hoaglin），定位是「值得调查」而不是自动删除 | 佐证「用中位数而不是均值做基线」；**没有改成 MAD**，理由见 iteration_notes |
| HubSpot 复利帖研究（2017，[HubSpot 博客](https://blog.hubspot.com/marketing/hubspot-blog-compounding-posts)及多方转述） | 约 1/10 的博客文章是「复利帖」，流量随时间增长，占总流量约 38%；这类文章多回答反复出现的常见问题 | 常青内容是少数；累计口径天然偏向老帖，必须提供同期比较 |
| 小红书 CES 社区互动评分（[人人都是产品经理](https://www.woshipm.com/ai/6201172.html)等第三方转述） | 点赞 1、收藏 1、评论 4、转发 4、关注 8；**平台没有官方公布** | 收藏/转发不该被忽略；只借用「收藏≈点赞、转发≈评论」的**相对比例** |
| Instagram 负责人 Mosseri（2025-01，[Social Media Today](https://www.socialmediatoday.com/news/instagram-shares-algorithm-insights-2025/738034/) 转述） | 最重要的三个排序信号：观看时长、likes per reach、sends per reach；sends（转发/私信分享）对触达非粉丝更重要 | 转发/分享应计入互动量 |

## 2. 数据源与平台规则的真实情况（2026-11-02）

- **本项目不接任何平台 API**，输入只有博主自己导出的 CSV，所以没有限流或接口改版风险；
  脆弱点在导出列名。v0.3.0 新增了收藏/转发/分享列的别名。
- **小红书**：2026-01-19 上线《社区公约 2.0》（价值观倡导，没有重复发布的细则）；
  2026-04-27 发布 AI 内容治理规则，点名「套用模板批量生产同质化内容」和「传授利用 AI 洗稿、
  规避审核」，按限制分发到封号分级处置。【媒体】[IT之家 2026-04-27](https://www.ithome.com/0/944/156.htm)
- **抖音**：2025-04-28 推出账号健康分（初始 100 分）和《"恶意营销号"治理规范》，
  点名「频繁发布抄袭搬运内容」「工业化生产和批量发布同质化内容」。【媒体】[IT之家 2025-04-28](https://www.ithome.com/0/849/480.htm)
- **「小红书 180 天内容指纹」查无官方出处**：v0.1.0–v0.2.0 的红线文案把它当事实写，
  本轮多次检索只找到经验文章，没有平台文档。v0.3.0 起红线改为引用上面两条可查证的规则，
  并说明「同账号自我重复的具体判定阈值平台没有公开」。
- **间隔取值**：各家给的回收间隔集中在 45-90 天，60-90 天最常见（UniLink、SocialBu 等），
  没有官方「安全阈值」。60 天默认值保留，文案改为「行业常见区间的下沿」，不再说成是
  某个平台规则的推导结果。

## 3. 可借鉴的逻辑 → 本项目落地（v0.3.0）

| 借鉴点 | 出处 | 落地 |
| --- | --- | --- |
| 最小帖龄 / 冷却期从**首发**算起 | Revive Old Posts 最小帖龄；SocialBu「新帖先观察 1-2 周」；OpenTweet 冷却按上次发布算 | 同帖再发间隔的起点改为 max(首发日, ledger 最近再发日)；发布不足 60 天的赢家进待定，并注明最早可排日 |
| 同时期 / 同帖龄基线、排除自身 | vidIQ「同一时间段」；Overseer age-matched、排除自身、20-30 条高置信 | 新增 `--baseline rolling`：取同平台发布日期最近的 N 条（默认 20），不含自身；报告检测「基线漂移」，并提示加跑滚动基线 |
| 中位数基线 + 3x 阈值 | Vamos 自身中位数；OutlierKit 3x+ 显著；Overseer 3-5x strong | 保留 3x + P75 默认值，现在有了外部依据 |
| 最小样本门槛 | Vamos ≥10 条；Overseer 10-19 条中等置信 | 保留 `--min-sample 10`；同时修复该参数没有传进报告文案的 bug |
| 回收次数上限 | CoSchedule 发送上限、SmarterQueue 过期、SocialBu 2-5 次、TryPost 6 轮 | 新增 `--max-recycles`（默认 0 = 不限，向后兼容） |
| 时效内容过滤 | SocialBu「跳过节日/活动帖」；social-calendar-builder「每次回收前重核日期价格」 | 标题出现年份/节日/活动/直播等词时，理由位标「疑似时效」，只提示不剔除，交给 Agent 和用户确认 |
| 收藏 / 转发计入互动 | 小红书 CES（第三方）、Mosseri sends per reach | 识别收藏、转发/分享列，权重分别跟点赞、评论相同；导出里没有这两列时结果和 v0.2.0 完全一样 |
| 变体轮换而不是原样重发 | UniLink（≥2-3 个变体）、ContentStudio Variations | 保留 Agent 按帖写 1-3 个变体方向；红线改为引用可查证的平台规则 |

## 4. 本项目差距（仍未做 / 不打算做）

- **没有帖子的时间序列快照**：Overseer 的严格做法是比较「发布第 T 天」的数据，CSV 导出
  通常只有当前累计值，所以滚动基线和日均口径都只是近似。
- **回流效果闭环**：SmarterQueue 有按轮次的数据，TryPost 提案里有跨轮次累计统计；
  本项目只能等博主下一期重新导出再对比，没有自动归因。
- **没有粉丝数 / 触达口径**：SocialBu 建议用互动率而不是绝对互动；导出里经常没有触达数，
  本项目只在账号内部比较，用滚动基线部分缓解粉丝量变化的影响。
- **时效判断只看标题**：关键词提示会有漏报和误报，正文里的时效信息看不到。

## 5. v0.1.0 首轮结论（2026-09-19，保留原文要点）

- 需求证据：HubSpot 称其约 76% 的月博客浏览量、92% 的线索来自旧帖（后续口径约 89%）；
  CoSchedule、ContentStudio、SmarterQueue 都把常青回收做成付费功能，G2/Capterra 上
  高频差评是「贵」，而且要 OAuth 绑定账号。这些数字当时取自公开页面，本轮没有逐一复核。
- 国内空白：小红书、抖音、公众号没有向这些海外工具开放发布 API；国内博主手工「删了重发」，
  这恰好是高风险动作。
- 定位：输入是本地导出、不需要授权；赢家自动检测而不是手动标记；输出是变体重发建议，
  不做自动发布。
