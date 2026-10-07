// Pixel 差异视图（差异图 + 差异清单）
//
// 用户 2026-10-07 要的：「把 md 文件与 svg/png 显示界面结合起来」。
//
// 干三件事：
//   ① 贡献一个**自定义编辑器**（viewType `pixelDiff.diffMd`），接管 `diff/diff-*.md`
//      ⇒ 打开清单时，左边就是那张叠合差异图（svg，矢量、可缩放），右边是清单。
//   ② 命令「比较两版」：从 `pixel-pcb-v*.fzz` 里选两版 ⇒ 跑 tools/diff_revs.py ⇒ 打开合并视图。
//   ③ 命令「比较两个文件」：fzz / svg 都行（svg 那侧用来比 Fritzing 导出的图）。
//
// 刻意**不做**的事（第一版求稳）：
//   · 不引任何依赖（纯 CommonJS，只要 node 内置模块）；
//   · webview **不开脚本**（enableScripts:false）⇒ 没有 CSP/nonce 那一摊事，也没有注入面；
//   · 不自己拼输出文件名 ✗ —— 生成完去 `diff/` 里挑**最新的 `diff-*.md`** ⇒
//     命名规则只有 diff_revs.py 一份实现（本仓老规矩：判据/公式只留一份）。

const vscode = require('vscode');
const cp = require('child_process');
const fs = require('fs');
const path = require('path');

const VIEW = 'pixelDiff.diffMd';
const PY = process.env.PIXEL_PY || 'python';

let outCh = null;

function log(s) {
	if (!outCh) outCh = vscode.window.createOutputChannel('Pixel 差异');
	outCh.appendLine(s);
}

/** 找到 `hardware/pixel`：先看 `<工作区>/hardware/pixel`，再看工作区根（单开 pixel 时）。 */
function pixelDir() {
	for (const f of vscode.workspace.workspaceFolders || []) {
		const a = path.join(f.uri.fsPath, 'hardware', 'pixel');
		if (fs.existsSync(path.join(a, 'tools', 'diff_revs.py'))) return a;
		if (fs.existsSync(path.join(f.uri.fsPath, 'tools', 'diff_revs.py'))) return f.uri.fsPath;
	}
	return null;
}

/** `pixel-pcb-v*.fzz` ⇒ 按版本号排（后缀如 `_byHand` 排在同号之后）。 */
function listVersions(dir) {
	const key = (n) => {
		const m = /-v(\d+)([\s\S]*)$/.exec(n.replace(/\.fzz$/, ''));
		return m ? [Number(m[1]), m[2] ? 1 : 0, m[2]] : [0, 0, n];
	};
	return fs.readdirSync(dir).filter((n) => /^pixel-pcb-v\d+.*\.fzz$/.test(n))
		.sort((a, b) => {
			const x = key(a), y = key(b);
			return (x[0] - y[0]) || (x[1] - y[1]) || String(x[2]).localeCompare(String(y[2]));
		});
}

/** 跑 diff_revs.py（日志进输出通道；PYTHONIOENCODING 必须给 —— 否则中文/✓ 会撞 GBK 控制台）。 */
function runDiff(dir, a, b) {
	return new Promise((resolve) => {
		log(`\n> ${PY} tools/diff_revs.py "${a}" "${b}"   （cwd=${dir}）`);
		cp.execFile(PY, ['tools/diff_revs.py', a, b], {
			cwd: dir,
			env: Object.assign({}, process.env, { PYTHONIOENCODING: 'utf-8' }),
			maxBuffer: 32 * 1024 * 1024
		}, (err, stdout, stderr) => {
			const txt = String(stdout || '') + String(stderr || '');
			log(txt.trim());
			resolve({ code: err ? (err.code === undefined ? 1 : err.code) : 0, text: txt });
		});
	});
}

/** `diff/` 里最新的 `diff-*.md`（刚跑完那个）。 */
function newestDiffMd(dir) {
	const d = path.join(dir, 'diff');
	if (!fs.existsSync(d)) return null;
	const hit = fs.readdirSync(d).filter((n) => /^diff-.*\.md$/.test(n))
		.map((n) => ({ n, t: fs.statSync(path.join(d, n)).mtimeMs }))
		.sort((a, b) => b.t - a.t);
	return hit.length ? path.join(d, hit[0].n) : null;
}

function esc(s) {
	return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** 极简 markdown ⇒ html（只应付 diff_revs.py 写出来的那几种：标题 / 列表 / 引用 / 行内）。 */
function mdToHtml(md) {
	const inline = (s) => esc(s)
		.replace(/`([^`]+)`/g, '<code>$1</code>')
		.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
	const out = [];
	let inUl = false;
	const closeUl = () => { if (inUl) { out.push('</ul>'); inUl = false; } };
	for (const raw of String(md).split(/\r?\n/)) {
		const line = raw.replace(/\s+$/, '');
		let m;
		if (!line.trim()) { closeUl(); continue; }
		if ((m = /^#\s+(.*)$/.exec(line))) { closeUl(); out.push(`<h1>${inline(m[1])}</h1>`); continue; }
		if ((m = /^##\s+(.*)$/.exec(line))) { closeUl(); out.push(`<h2>${inline(m[1])}</h2>`); continue; }
		if ((m = /^###\s+(.*)$/.exec(line))) { closeUl(); out.push(`<h3>${inline(m[1])}</h3>`); continue; }
		if ((m = /^>\s?(.*)$/.exec(line))) { closeUl(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
		if ((m = /^\s*[-*]\s+(.*)$/.exec(line))) {
			if (!inUl) { out.push('<ul>'); inUl = true; }
			out.push(`<li>${inline(m[1])}</li>`);
			continue;
		}
		closeUl();
		out.push(`<p>${inline(line)}</p>`);
	}
	closeUl();
	return out.join('\n');
}

function html(webview, mdText, imgUri, imgName, hint) {
	const csp = `default-src 'none'; img-src ${webview.cspSource} data:; style-src 'unsafe-inline';`;
	return `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<style>
  body { margin:0; font-family: var(--vscode-font-family); color: var(--vscode-editor-foreground); }
  .wrap { display:flex; height:100vh; }
  .pane { overflow:auto; }
  .left { flex:2 1 0; background:#ffffff; display:flex; align-items:flex-start; justify-content:center;
          padding:8px; box-sizing:border-box; }
  .left img { max-width:100%; height:auto; }
  .right { flex:1 1 0; padding:10px 14px; border-left:1px solid var(--vscode-panel-border); }
  .bar { font-size:12px; opacity:.75; padding:4px 8px; border-bottom:1px solid var(--vscode-panel-border); }
  h1 { font-size:1.15em; } h2 { font-size:1.05em; margin-top:1.1em; } h3 { font-size:1em; }
  code { background: var(--vscode-textCodeBlock-background); padding:0 3px; border-radius:3px; }
  blockquote { margin:.4em 0; padding-left:8px; border-left:3px solid var(--vscode-panel-border); opacity:.85; }
  ul { padding-left:1.2em; margin:.2em 0; }
  .hint { color: var(--vscode-errorForeground); }
</style></head><body>
<div class="wrap">
  <div class="pane left">${imgUri
		? `<img src="${imgUri}" alt="${esc(imgName || 'diff')}">`
		: `<div class="hint" style="padding:16px">${esc(hint || '还没生成差异图')}</div>`}</div>
  <div class="pane right">
    <div class="bar">${imgUri ? esc(imgName) : '（无图）'}</div>
    ${mdToHtml(mdText)}
  </div>
</div>
</body></html>`;
}

class DiffEditor {
	constructor(context) { this.context = context; }

	async resolveCustomTextEditor(document, panel) {
		const mdPath = document.uri.fsPath;
		const dir = path.dirname(mdPath);
		const stem = path.basename(mdPath).replace(/\.md$/, '');
		const svg = path.join(dir, stem + '.svg');
		const png = path.join(dir, stem + '.png');
		const img = fs.existsSync(svg) ? svg : (fs.existsSync(png) ? png : null);
		panel.webview.options = { enableScripts: false, localResourceRoots: [vscode.Uri.file(dir)] };
		const draw = () => {
			const uri = img ? panel.webview.asWebviewUri(vscode.Uri.file(img)) : null;
			panel.webview.html = html(panel.webview, document.getText(), uri, img ? path.basename(img) : '',
				`这份清单旁边没有同名图 ⇒ 先跑 py tools\\diff_revs.py，或直接对我用命令「比较两版」`);
		};
		draw();
		this.context.subscriptions.push(
			vscode.workspace.onDidChangeTextDocument((e) => {
				if (e.document.uri.toString() === document.uri.toString()) draw();
			}),
			vscode.workspace.onDidSaveTextDocument((e) => {
				if (e.uri.toString() === document.uri.toString()) draw();
			})
		);
	}
}

async function cmdCompare(context) {
	const dir = pixelDir();
	if (!dir) return void vscode.window.showErrorMessage('找不到 hardware/pixel/tools/diff_revs.py');
	const vers = listVersions(dir);
	if (vers.length < 2) return void vscode.window.showErrorMessage('这个目录里少于两版 fzz');
	const pick = (def) => vscode.window.showQuickPick(vers, { placeHolder: `选一版（默认 ${def}）` })
		.then((v) => v || def);
	const a = await pick(vers[vers.length - 2]);
	const b = await pick(vers[vers.length - 1]);
	await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `差异图：${a} ⇒ ${b}` },
		() => runDiff(dir, a, b));
	const md = newestDiffMd(dir);
	if (!md) return void vscode.window.showErrorMessage('跑完了但没有 diff-*.md，见「Pixel 差异」输出通道');
	await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(md), VIEW);
}

async function cmdCompareFiles() {
	const dir = pixelDir();
	if (!dir) return void vscode.window.showErrorMessage('找不到 hardware/pixel/tools/diff_revs.py');
	const one = await vscode.window.showOpenDialog({
		canSelectMany: false, openLabel: '选第一个（A）', defaultUri: vscode.Uri.file(dir),
		filters: { 'fzz / svg': ['fzz', 'svg'] }
	});
	if (!one || !one.length) return;
	const two = await vscode.window.showOpenDialog({
		canSelectMany: false, openLabel: '选第二个（B）', defaultUri: vscode.Uri.file(dir),
		filters: { 'fzz / svg': ['fzz', 'svg'] }
	});
	if (!two || !two.length) return;
	await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: '差异图' },
		() => runDiff(dir, one[0].fsPath, two[0].fsPath));
	const md = newestDiffMd(dir);
	if (md) {
		await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(md), VIEW);
	} else {
		// 两边都是 svg 时不出清单，只出图 ⇒ 直接把图打开
		const png = path.join(dir, 'diff');
		const hit = fs.existsSync(png)
			? fs.readdirSync(png).filter((n) => /^diff-.*\.png$/.test(n))
				.map((n) => ({ n, t: fs.statSync(path.join(png, n)).mtimeMs })).sort((x, y) => y.t - x.t)
			: [];
		if (hit.length) await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(path.join(png, hit[0].n)));
		else vscode.window.showErrorMessage('没找到新生成的图，见「Pixel 差异」输出通道');
	}
}

function activate(context) {
	context.subscriptions.push(
		vscode.commands.registerCommand('pixelDiff.compare', () => cmdCompare(context)),
		vscode.commands.registerCommand('pixelDiff.compareFiles', () => cmdCompareFiles()),
		vscode.window.registerCustomEditorProvider(VIEW, new DiffEditor(context),
			{ webviewOptions: { retainContextWhenHidden: true } })
	);
}

function deactivate() { }

// 把**纯函数**引出来给单测用（`_work/_test_ext.js`）——
// 扩展本体没法在这儿跑（要 VS Code 的扩展宿主），但"选版本 / 找最新清单 / 清单转 HTML"
// 这几件是纯逻辑，能单独验 —— 免得只靠"装上去点一下看看"。
module.exports = { activate, deactivate, _pure: { listVersions, newestDiffMd, mdToHtml } };
