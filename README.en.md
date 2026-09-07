# GPT-6 Battle-Tested Resources

Free resources from the working session about websites, UI consoles, agents and workflows. This repository links to the open-source tools at reviewed commits and includes a sanitized, generic edition of the SEO agent built in the video.

> This is an independent community resource, not an official OpenAI repository. Review third-party code before running it.

## Quick start

```bash
git clone https://github.com/novusordos666/gpt6-battle-tested-resources.git
cd gpt6-battle-tested-resources/seo-agent
cp config.example.json config.json
python3 -m venv .venv
.venv/bin/pip install -e .
./run doctor
```

The example uses reserved example domains. Replace them before crawling. Production publishing is disabled globally and per site.

## Included resources

- [NVIDIA SkillSpector](https://github.com/NVIDIA/SkillSpector/tree/88eedca754c74260dfae4e6d6cfb293a0053c908) — inspect agent skills. A scan is not a safety guarantee.
- [no-ai-slop](https://github.com/petergyang/no-ai-slop/tree/000650b156983f5159695b441477f4e63b25dc85) — improve generic AI-written copy.
- [phone-harness](https://github.com/ShawnPana/phone-harness/tree/6e47f24cd1d6110e9c72dc2bfe559d2ec709e56d) — operate and test mobile interfaces. Disable telemetry if you do not want it.
- [video-use](https://github.com/browser-use/video-use/tree/9575612f066aa517354790a645fd90f9f95a743b) — agentic video analysis. Transcription can upload data to ElevenLabs when used.
- [Comp AI CRM](https://github.com/trycompai/crm/tree/6d4793dd6d7aeea91aa6a034e00b17d7408a2d08) — CRM backend for the optional adapter. Source link only; the local automated review was incomplete, so manual review is required.

The exact list is in [`resources.json`](resources.json), with license boundaries in [`THIRD_PARTY.md`](THIRD_PARTY.md).

## SEO agent

[`seo-agent/`](seo-agent/) provides crawling, GSC/GA4 imports, evidence-based opportunity scoring, content validation, disabled-by-default publishing adapters, an optional local CRM ledger and an installable agent skill. It contains no private domains, customer data, credentials, production content, databases or deployment settings from the original environment.

The original code and documentation in this repository are MIT licensed. External projects retain their own licenses.
