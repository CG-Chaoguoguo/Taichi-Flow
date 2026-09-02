"""Render self-contained HTML for the 20260829 Chamoli optimization review."""
from __future__ import annotations

import base64
import html
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHOTS = HERE / "screenshots"
OUT = HERE / "20260829_chamoli_opt_review.html"


def _img(name: str, alt: str) -> str:
    path = SHOTS / name
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return (
        f'<figure class="shot"><img src="data:image/png;base64,{b64}" alt="{html.escape(alt)}"/>'
        f"<figcaption>{html.escape(alt)}</figcaption></figure>"
    )


def main() -> None:
    runtime = _img("chamoli_opt_review_runtime_params.png", "参数页「运行时」三开关：异步写盘、采样间隔 20 步、中间 GeoTIFF")
    diag = _img("chamoli_opt_review_diagnostics_card.png", "结果页数值运行诊断卡：cuda/f32，守恒通过")
    report_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Chamoli 优化科学性与可靠度审阅 · 2026-08-29</title>
<style>
:root {{
  --bg: #0f1419; --panel: #172027; --ink: #e7eef4; --muted: #9aa8b4;
  --line: #2a3842; --ok: #3dd68c; --warn: #e7b549; --bad: #f07178;
  --accent: #7aa2f7;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.65 "Segoe UI", "Noto Sans SC", "Microsoft YaHei", sans-serif; }}
main {{ max-width: 1080px; margin: 0 auto; padding: 32px 24px 80px; }}
h1 {{ font-size: 1.7rem; margin: 0 0 8px; }}
h2 {{ font-size: 1.25rem; margin: 36px 0 12px; border-bottom: 1px solid var(--line); padding-bottom: 6px; }}
h3 {{ font-size: 1.05rem; margin: 22px 0 8px; }}
p, li {{ color: var(--ink); }}
.muted {{ color: var(--muted); }}
.lead {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; }}
.lead ol {{ margin: 8px 0 0 20px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; margin: 12px 0 20px; }}
th, td {{ border: 1px solid var(--line); padding: 7px 8px; vertical-align: top; text-align: left; }}
th {{ background: #1d2a33; color: #d5e4ef; }}
tr:nth-child(even) td {{ background: #141c22; }}
code {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 0.88em;
  background: #10181d; padding: 1px 5px; border-radius: 4px; }}
.badge {{ display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 0.8rem; }}
.ok {{ background: #163528; color: var(--ok); }}
.warn {{ background: #3a2e12; color: var(--warn); }}
.shot {{ margin: 16px 0; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }}
.shot img {{ display: block; width: 100%; height: auto; }}
.shot figcaption {{ padding: 8px 12px; color: var(--muted); font-size: 0.88rem; }}
footer {{ margin-top: 40px; color: var(--muted); font-size: 0.85rem; }}
</style>
</head>
<body>
<main>
<h1>Chamoli 优化科学性与可靠度审阅</h1>
<p class="muted">2026-08-29 · 相对 HEAD <code>aa34929</code> 未提交改动 · 不声称 CUDA–Fortran 数值对等</p>

<div class="lead">
<strong>结论先行</strong>
<ol>
<li><span class="badge ok">科学性未改</span> 优化不改变 Chamoli CUDA 方程、接受/拒绝、体积账本与五变体公式。A/B 4 帧 × 16 族 ASCII 逐格全同。</li>
<li><span class="badge warn">GPU 占用未升</span> 同代码 t=180 fp64：OPT 419 s / 中位 38%，BASELINE 414 s / 中位 37%。瓶颈是 kernel 粒度与 host 间隙，不是 I/O。</li>
<li><span class="badge ok">方法学符合</span> 五变体、<code>cvero→rhoero</code>、入流出流账本、<code>fssimul=F</code> 仍对照 Chamoli <code>dfs.F90</code>。这不是数值 parity。</li>
<li>未发现必须立刻修复的正确性缺陷。观测层缺口见第 9 节。</li>
</ol>
</div>

<h2>1. 审阅范围</h2>
<table>
<tr><th>项</th><th>值</th></tr>
<tr><td>Python / GPU</td><td>3.11.9 · RTX 3080 Ti 12 GB · Taichi 1.7.4</td></tr>
<tr><td>Fortran</td><td><code>Chamoli-EDDA file/dfs.F90</code> · <code>edda main program.F90</code></td></tr>
<tr><td>核心 diff</td><td><code>dfs_dynamic_wave.py</code>、<code>edda_solver.py</code>、<code>async_result_writer.py</code>、<code>result_exporter.py</code>、<code>sim_config.py</code></td></tr>
<tr><td>A/B</td><td>t=180、tout=45、4 帧、fp64；OPT=async+stride20；BASELINE=同步+stride1+诊断捕获开</td></tr>
<tr><td>子审阅</td><td>Grok 4.6 xHigh：DFS 热路径、异步输出、EDDA 方法学</td></tr>
</table>

<h2>2. DFS 热路径判定</h2>
<table>
<tr><th>改动</th><th>判定</th><th>Fortran</th><th>风险</th></tr>
<tr><td><code>step_result_pack</code> / <code>volume_snapshot_pack</code></td><td>数值不变</td><td><code>dfs.F90:797-801</code>、<code>1137-1258</code></td><td>低</td></tr>
<tr><td><code>_reset_candidate_step_scalars</code></td><td>数值不变</td><td><code>:797-801</code></td><td>低</td></tr>
<tr><td>体积清零折入 <code>_accumulate_volume_balance</code></td><td>仅比特级</td><td><code>:1137-1235</code></td><td>低</td></tr>
<tr><td>体积计数折入 <code>_commit_step</code></td><td>仅比特级</td><td><code>:1251-1257</code>、<code>:1274-1276</code></td><td>低</td></tr>
<tr><td>depo-velocity 默认关</td><td>数值不变</td><td>Fortran 无此快照；生产速度是 <code>fv</code></td><td>低</td></tr>
<tr><td>跳过 <code>vdir_legacy</code> 同步</td><td>数值不变</td><td>该场只写不读</td><td>低</td></tr>
<tr><td>接受路径空 <code>first_reject</code></td><td>数值不变</td><td>仅观测；拒步仍展开</td><td>低</td></tr>
</table>
<p>折叠体积 kernel 最多引入 IEEE 发射融合差；本窗口 ASCII 未测到任何非零差。</p>

<h2>3. 输出管线</h2>
<table>
<tr><th>项</th><th>判定</th><th>要点</th></tr>
<tr><td>写脏帧</td><td>安全</td><td>入队 <code>np.array(..., copy=True)</code>；单写线程 FIFO；满队列反压</td></tr>
<tr><td>flush</td><td>安全</td><td><code>run()</code> <code>finally</code> <code>close()</code> join；直接 <code>_output_results</code> 同步回退</td></tr>
<tr><td><code>numerical_observe_stride</code></td><td>物理安全</td><td>账本每步累积；stride 只读回诊断。拒步/输出/收尾强制观测</td></tr>
<tr><td>诊断极值</td><td>报告层风险</td><td>未采样接受步可能漏记 <code>|rel|&gt;1e-3</code>；期末全局账本仍 live</td></tr>
<tr><td>ASCII</td><td>数值安全</td><td><code>%.6f</code>；Windows 可能 LF vs 旧 CRLF</td></tr>
</table>

<h2>4. Chamoli 变体符合性</h2>
<table>
<tr><th>变体 / 条件</th><th>判定</th><th>Fortran 行</th></tr>
<tr><td><code>arithmetic_mean_chamoli</code></td><td>符合</td><td><code>:623</code> 面积 <code>hbar</code>；<code>:634</code> 面积 <code>cvbar</code>；<code>:672</code> 算术 <code>frhobar</code></td></tr>
<tr><td><code>debrisflowmanning_cvtol</code></td><td>符合</td><td>侵蚀 <code>:417-421</code>；面通量 <code>:667-670</code> 空操作</td></tr>
<tr><td><code>zero_dry_face_chamoli</code></td><td>符合</td><td><code>:735-737</code> 符号翻转前置零</td></tr>
<tr><td><code>velocity_ratio_chamoli</code></td><td>符合</td><td><code>:720-732</code> 速度比人工粘</td></tr>
<tr><td><code>signed_mean_chamoli</code></td><td>符合</td><td><code>:209-212</code> 有符号 <code>vx,vy</code>，对角 <code>0.707</code></td></tr>
<tr><td><code>cvero→rhoero</code></td><td>符合</td><td><code>:444</code>、<code>:572</code>；<code>rhodepo</code> 仍 <code>cvstar</code></td></tr>
<tr><td>入流出流账本</td><td>符合</td><td><code>:1176-1241</code>，相对误差 0.001</td></tr>
<tr><td><code>fssimul=F</code></td><td>符合</td><td>主程序 <code>:503</code> 关 UNSFIN；<code>triggerslide</code> 仍一次注入</td></tr>
</table>
<p class="muted">HEAD 求解器 diff 没有改写这些算术。既有离散残差（如 t=45 流速 max_abs≈27.7）不是本轮引入。</p>

<h2>5. GPU A/B</h2>
<table>
<tr><th>指标</th><th>OPT</th><th>BASELINE</th><th>Δ</th></tr>
<tr><td>墙钟</td><td>419.4 s</td><td>414.0 s</td><td>OPT +1.3%</td></tr>
<tr><td>GPU min/mean/median/p90/max</td><td>1 / 37.6 / <strong>38</strong> / 42 / 49</td><td>2 / 36.1 / <strong>37</strong> / 41 / 56</td><td>中位 +1 pp</td></tr>
<tr><td>显存 mean/max</td><td>5234 / 5529 MiB</td><td>5414 / 5743 MiB</td><td>OPT 略低</td></tr>
<tr><td>输出</td><td>435 MB · 76 文件</td><td>435 MB</td><td>同</td></tr>
<tr><td>写盘突发</td><td>≈164 / 250 / 332 / 414 s</td><td>≈162 / 246 / 327 / 410 s</td><td>均在输出时刻</td></tr>
</table>
<p>四帧窗口里磁盘远小于 400 s 求解。占用停在约 37%，主因是短 kernel 与 host 发射，不是 I/O。UI t=900 的 15 s 中位 7% 过粗，不能与本 1 s 采样直接比。</p>

<h2>6. 数值等价</h2>
<p>t=45/90/135/180 × 16 族：缺失 0，非零差 0，判定 <span class="badge ok">identical</span>。相对 Fortran 的 t=45 <code>Flow_depth max_abs=0.075856</code> 两跑相同，属既有残差。</p>

<h2>7. 回归测试</h2>
<p>Python 3.11 复跑 DFS / 数值诊断 / 边界出流 / 分区双层 / 运行时 I/O：<strong>101 passed</strong>，1 warning（Taichi locale 弃用），1385 s。</p>

<h2>8. 浏览器核验</h2>
<p>参数页「运行时」三开关可见：异步写盘=true，采样间隔=20 步，中间 GeoTIFF=true。已完成方案只读。诊断卡：14682 接受 / 1451 拒绝，全局账本 −8.92e−7 通过。</p>
{runtime}
{diag}

<h2>9. 总评</h2>
<ul>
<li><strong>科学性</strong>：未改。方法学分支与账本仍在；A/B ASCII 全同。</li>
<li><strong>GPU</strong>：本窗口开关回退没有实质抬升占用。再优化应针对 kernel 合并 / 减少逐步 host 同步，而不是再关 I/O。</li>
<li><strong>研究可用性</strong>：活动 Chamoli 开关与命名变体对齐 <code>dfs.F90</code> 引用行。继续「不声称 parity」。</li>
<li><strong>不修清单</strong>：接受路径空 <code>first_reject</code>；stride 稀释诊断极值；rholimit 一次播种 vs Fortran 每步重算（<code>:371</code>，既有）。</li>
</ul>

<footer>自包含 HTML。源稿 <code>docs/audit/20260829_chamoli_opt_review.md</code>。产物 <code>artifacts/chamoli_ab_opt_t180</code>、<code>chamoli_ab_baseline_t180</code>、<code>chamoli_ab_opt_vs_baseline_t180.json</code>。</footer>
</main>
</body>
</html>
"""
    OUT.write_text(report_html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
