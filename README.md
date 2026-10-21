# Zagonel Smart Banho para Home Assistant

Integração para o chuveiro **Zagonel Smart Banho (Ducali)**. Usa a mesma conta do aplicativo Smart Banho: você informa e-mail e senha e o chuveiro aparece sozinho no Home Assistant, com estado em tempo real, histórico de banhos e controles.

> Projeto independente, sem vínculo com a Zagonel.

## O que ela traz

**Tempo real** (o chuveiro avisa na hora pela nuvem da Zagonel):

- Chuveiro ligado / desligado
- Temperatura da água, de entrada e alvo
- Vazão (L/min), potência (W), tensão (V), sinal Wi-Fi

**Banhos** (histórico da conta):

- Último banho: início, duração, água, energia, custo, temperatura média, vazão e potência médias
- Hoje e no mês: número de banhos, água, energia, custo e tempo total
- Energia e água do mês prontas para o **painel de Energia**

**Controles** (só funcionam com o chuveiro desligado, regra do próprio aparelho):

- Temperatura dos Presets 1 a 4
- Modo de controle (manual/automático)
- LED: modo (pela potência, pela temperatura, cor fixa) e cor
- Volume do som
- Controle dos pais: modo e limite de tempo

O custo é calculado com os preços de água e energia cadastrados no app.

## Instalação (HACS)

1. HACS → menu ⋮ → **Repositórios personalizados**
2. Cole a URL deste repositório e escolha o tipo **Integração**
3. Procure **Zagonel Smart Banho** no HACS e instale
4. Reinicie o Home Assistant
5. **Configurações → Dispositivos e serviços → Adicionar integração → Zagonel Smart Banho**
6. Informe o e-mail e a senha do app Smart Banho

Se você usava a integração antiga `homeassistant-zagonel`, remova-a: ela usa um servidor que a Zagonel desativou.

## Automações

Use a entidade **Chuveiro ligado** ou os eventos:

| Evento | Quando | Dados |
|---|---|---|
| `zagonel_smartbanho_banho_iniciado` | a água começa a correr | `chuveiro`, `temperatura_alvo_c` |
| `zagonel_smartbanho_banho_finalizado` | o banho é registrado na nuvem (até ~1 min após desligar) | `duracao_s`, `agua_l`, `energia_kwh`, `custo`, `temperatura_c`, ... |

Exemplo: avisar quando o banho passar de 10 minutos.

```yaml
automation:
  - alias: Banho longo
    triggers:
      - trigger: state
        entity_id: binary_sensor.ducali_chuveiro_ligado
        to: "on"
        for: "00:10:00"
    actions:
      - action: notify.notify
        data:
          message: "O banho já passou de 10 minutos"
```

Exemplo: registrar o custo de cada banho.

```yaml
automation:
  - alias: Custo do banho
    triggers:
      - trigger: event
        event_type: zagonel_smartbanho_banho_finalizado
    actions:
      - action: notify.notify
        data:
          message: >
            Banho de {{ (trigger.event.data.duracao_s / 60) | round(1) }} min,
            {{ trigger.event.data.agua_l }} L, R$ {{ trigger.event.data.custo }}
```

## Observações

- O chuveiro só manda o status ao vivo quando alguém pede; a integração pede a cada 15 segundos (como o app). Por isso o "ligado" aparece em até ~15 s depois de abrir a água.
- O chuveiro não manda aviso de "desliguei": ele é considerado desligado 90 segundos depois do último status (durante o banho ele às vezes fica até ~45 s sem responder).
- Com o chuveiro ligado, os controles ficam indisponíveis, porque o aparelho ignora alterações durante o banho. A temperatura nova vale a partir do próximo banho.
- Os nomes das entidades seguem o idioma do Home Assistant (português ou inglês).
