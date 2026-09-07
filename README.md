# GPT-6 Battle-Tested Resources

De gratis resources uit de werksessie over websites, UI-consoles, agents en workflows. Deze repository bundelt de gebruikte open-source tools als controleerbare, vastgepinde links en bevat een opgeschoonde, generieke versie van de SEO-agent uit de video.

> Dit is een onafhankelijke community-resource en geen officiële OpenAI-repository. Controleer externe code altijd zelf voordat je die uitvoert.

## Snel starten

```bash
git clone https://github.com/novusordos666/gpt6-battle-tested-resources.git
cd gpt6-battle-tested-resources/seo-agent
cp config.example.json config.json
python3 -m venv .venv
.venv/bin/pip install -e .
./run doctor
```

De voorbeeldconfiguratie gebruikt alleen voorbeelddomeinen. Vervang die eerst door je eigen domeinen. Publiceren staat op twee niveaus uit: globaal én per website.

## Resources uit de video

| Resource | Waarvoor | Vastgepinde versie | Reviewnotitie |
|---|---|---|---|
| [NVIDIA SkillSpector](https://github.com/NVIDIA/SkillSpector/tree/88eedca754c74260dfae4e6d6cfb293a0053c908) | Skills statisch en met modelanalyse inspecteren | `88eedca` | Zelf blijven beoordelen; een scan is geen veiligheidsgarantie. |
| [no-ai-slop](https://github.com/petergyang/no-ai-slop/tree/000650b156983f5159695b441477f4e63b25dc85) | Minder generieke AI-copy schrijven | `000650b` | Kleine skill; lokaal beoordeeld. |
| [phone-harness](https://github.com/ShawnPana/phone-harness/tree/6e47f24cd1d6110e9c72dc2bfe559d2ec709e56d) | Mobiele interfaces bedienen en testen | `6e47f24` | Telemetrie bewust uitschakelen als je die niet wilt. |
| [video-use](https://github.com/browser-use/video-use/tree/9575612f066aa517354790a645fd90f9f95a743b) | Video analyseren met browser/agent-workflows | `9575612` | Lokaal gebruiken; transcriptie kan data naar ElevenLabs sturen wanneer je die functie inzet. |
| [Comp AI CRM](https://github.com/trycompai/crm/tree/6d4793dd6d7aeea91aa6a034e00b17d7408a2d08) | Open-source CRM-backend voor de optionele adapter | `6d4793d` | Alleen bronlink: de lokale automatische scan was onvolledig, dus handmatige review vereist. |

De exacte machineleesbare lijst staat in [`resources.json`](resources.json). Licenties en grenzen staan in [`THIRD_PARTY.md`](THIRD_PARTY.md).

## Meegeleverde SEO-agent

[`seo-agent/`](seo-agent/) bevat:

- technische crawl en sitemap-inventarisatie;
- read-only imports voor Google Search Console en GA4;
- opportunity scoring op basis van waargenomen data;
- contentvalidatie met bron- en reviewchecks;
- uitgeschakelde Payload- en static-site publishing adapters;
- een optionele lokale CRM-ledger en loopback-only intake;
- een installeerbare agent-skill.

Er zijn geen interne domeinen, klantgegevens, credentials, content, databases of deployment-instellingen uit de oorspronkelijke omgeving opgenomen.

English documentation: [README.en.md](README.en.md).

## Licentie

De eigen code en documentatie in deze repository vallen onder MIT. Externe projecten behouden hun eigen licenties.
