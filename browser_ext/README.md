# jb-ape Session Bridge（浏览器插件）

装在你**自己已登录**的浏览器里，让 jb-ape 的安全用例直接跑在真实会话中——
不需要把账号密码交给测试工具，也不需要维护独立的自动化浏览器。

全程只与本机 `127.0.0.1:8765` 通信，没有任何数据出网。

## 安装（一次性，约 1 分钟）

1. 打开 Chrome / Edge，地址栏输入 `chrome://extensions`（Edge 为 `edge://extensions`）。
2. 右上角打开 **开发者模式**。
3. 点击 **加载已解压的扩展程序**，选择本目录（`browser_ext/`）。
4. 在浏览器里**正常登录你要测试的 Agent 页面**，保持该标签页在前台。

## 使用

在终端运行（引擎会自动启动本地桥并等插件接入）：

```bash
jb-ape qa --url https://你的agent页面/ --adapter ext
```

运行期间：

- **保持目标标签页在前台**（插件在可见页面上查找输入框更可靠）；
- 引擎每条用例会刷新一次页面（大多数聊天 UI 会因此开启新会话，保证用例间互不污染）；
- 结束后终端输出 QA 报告，`--out` 目录会落 md/json 文件。

## 输入框/回复区识别失败？

打开插件详情 → 扩展程序选项（或右键插件图标 → 选项），按域名填 CSS 选择器：

```json
{
  "chat.example.com": {
    "inputSelector": "textarea#prompt",
    "sendSelector": "button[aria-label='Send']",
    "replySelector": "[data-role='assistant']"
  }
}
```

## 工作原理（给安全评审）

- `background.js`（Service Worker）轮询本机 `127.0.0.1:8765/poll` 领取用例；
- `content.js`（隔离世界）把用例输入页面聊天框并等待回复稳定；
- `inject.js`（页面主世界）包装 `fetch`/`XMLHttpRequest`，把页面背后的
  JSON API 响应体作为证据回传（证据可信度：API > DOM）；
- 权限最小化：`storage`（保存站点选择器配置）、`tabs`（定位目标标签页）、
  `http://127.0.0.1/*`（仅本机回环请求）。

## 卸载

`chrome://extensions` 中移除即可；无任何残留（配置存于扩展自身 storage）。
