# Capturing traffic

proxy2model reads traffic you already captured, or records your own browser. Only capture traffic you are
authorized to record. Everything runs locally.

## Burp Suite

1. Set **Target > Scope** and browse the app through Burp as the role you want to capture.
2. In **Proxy > HTTP history**, select all, right-click, **Save items**. Keep base64 encoding on.

```bash
proxy2model history.xml -w shop
```

Burp Community is enough. A **Logger++ CSV** works too (`--skip-tools Scanner` drops scanner rows).

## HAR (browser, ZAP, mitmproxy, Hetty, Charles)

```bash
proxy2model session.har -w shop
```

In a browser: DevTools, Network, *Save all as HAR with content*. Requests that never got a response are skipped.

## Your own browser

`browse` opens a browser and records what you do in it. The model rebuilds as you go; no proxy,
no export, no certificate to install.

```bash
proxy2model browse
```

It asks for the app's URL, the scope (default `*.<its domain>`: the domain and its subdomains), a
name for the model, and the mode:

- **passive** records only what you do.
- **active** also crawls the app in a background tab of the same browser, so it shares your login.
  It stays in scope, never clicks logout- or delete-looking controls and never submits a password
  form. Only for apps you are authorized to test.

Every tab, popup, frame and worker is recorded from its first request; nothing out of scope is
recorded, and nothing is blocked. Close the window (or Ctrl-C) to finish: the last build prints
where the report is. Each exchange is masked on arrival and only the masked record is saved
(`inputs/browse.jsonl`), so the next session adds to the same model.

Everything can go on the command line instead:

```bash
proxy2model browse https://app.example.com --scope '*.example.com' -w shop --active --yes --role user
```

Needs Chrome, Chromium, Edge or Brave (found automatically, or `--chrome PATH`). The browser uses a
fresh profile that is deleted afterwards.

## Roles

Capture once per role, then compare:

```bash
proxy2model user.xml  -w shop --role user
proxy2model admin.xml -w shop --role admin
proxy2model cross-role shop --low user --high admin
```

Rebuilding a role replaces only that role; a build without `--role`, or with `--fresh`, starts over.

## Keep exporting

`proxy2model watch FOLDER -w shop` builds every new export dropped into the folder and prints what changed.

## No proxy

`proxy2model crawl https://shop.example.com/ -w shop --yes` drives a real browser. See [crawling.md](crawling.md).
