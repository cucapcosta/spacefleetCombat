# Campanha single-player com batalhas manuais

Data: 2026-09-24
Status: Aprovada pelo usuário em 2026-09-24

## Objetivo e escopo

Entregar um ciclo local jogável: montar a frota, controlar suas naves contra a
IA, receber recompensas, reparar e melhorar a frota e disputar o próximo
confronto. O jogador deve conseguir testar as mecânicas durante a campanha.

O usuário escolheu campanha linear com controle manual, recompensas, reparos e
evolução da frota e aprovou esta especificação. As regras numéricas e os limites
abaixo definem a primeira entrega e podem ser ajustados após testes de jogo.

O objetivo posterior continua sendo completar as mecânicas e a campanha
single-player. Esta especificação cobre a primeira entrega jogável; mapa
estratégico, economia territorial, narrativa e armas ainda incompletas serão
entregas posteriores. Não há trabalho de multiplayer nesta entrega.

## Abordagem

| Alternativa | Consequência |
|---|---|
| Campanha manual sobre o resolvedor existente — proposta | Reutiliza regras e permite testar combate e progressão desde a primeira entrega |
| Implementar primeiro o gauntlet automático antigo | Produz um ciclo mais curto, mas não atende ao controle manual escolhido |
| Completar todas as mecânicas antes da campanha | Adia o primeiro ciclo jogável e o feedback de balanceamento |

O documento de gauntlet de 2026-08-04 fica como referência histórica. Suas
premissas de batalha automática, identidade por posição e loja baseada apenas
no valor total da frota não se aplicam a esta campanha. Não modificar seus
arquivos durante esta entrega.

## Fluxo do jogador

1. Escolher Nova campanha ou Continuar campanha no menu local.
2. Na criação, escolher Imperial Navy ou Chaos, nome e seed opcional; montar
   uma frota válida com orçamento inicial de 800 créditos.
3. Ver confronto, frota, danos, comandante e saldo; comprar, reequipar e reparar.
4. Iniciar a batalha, dar ordens às naves e usar as habilidades disponíveis.
5. Receber relatório de vitória ou derrota, baixas, dano, XP e créditos.
6. Após uma vitória, voltar ao intervalo ou concluir a campanha no quinto confronto.

Continuar restaura o último intervalo salvo. O primeiro save ocorre depois da
montagem inicial. Há autosave após cada operação econômica confirmada e após
o fechamento de cada batalha, além de comando explícito para salvar no intervalo.

Salvar no meio do combate fica para uma entrega posterior. Ao sair durante uma
batalha, informar que Continuar retorna ao intervalo anterior. A seed permite
repetir o confronto para testar; não há exigência de impedir recarga de saves.

## Regras da primeira campanha

| Regra | Proposta |
|---|---|
| Duração | Cinco confrontos; vencer o quinto conclui a campanha |
| Objetivo de batalha | Eliminar a frota adversária |
| Derrota | Frota do jogador eliminada, rendição ou limite de 60 turnos sem vitória |
| Eliminação simultânea | Derrota |
| Inimigos | Cinco frotas predefinidas por facção, de dificuldade crescente, validadas com as regras existentes |
| Controle | Jogador comanda sua frota; IA controla somente a frota adversária |
| Recompensa | Vitória: 100 créditos + 20 por nave inimiga destruída + 15 por nave do jogador viva no fechamento; derrota: zero |
| Saldo inicial | Créditos não gastos na montagem ficam disponíveis |
| Perdas | Naves destruídas saem permanentemente do roster |
| Comandante | Identidade, XP, nível, habilidades, passivas e traits persistem |
| Flagship destruído | Comandante sobrevive nesta versão; selecionar outro sobrevivente antes do próximo combate |
| Crew | Veterania persiste, sem incremento duplicado ao fechar a batalha |

Os valores são parâmetros de balanceamento em um único lugar. As frotas inimigas
devem usar apenas equipamentos suportados e oferecer confrontos reproduzíveis.
Testes verificam legalidade e progressão de custo; dificuldade real exige jogar.

## Combate local

Adicionar um controlador local síncrono que coordene entrada, apresentação e
turnos. Reutilizar `GameState`, `add_custom_fleet`, `validate_command`,
`AIController`, `resolve_turn` e os renderizadores existentes. Esses módulos
podem continuar em `net/` nesta entrega: sua localização não exige conexão.

O controlador coleta ordens válidas das naves e até uma ordem de habilidade do
comandante por turno, permite revisar antes de confirmar, gera as ordens da IA
e chama `resolve_turn(state, commands, ability_orders)`. Inspeção, ajuda e
entradas inválidas não avançam o turno. A IA deve receber explicitamente os IDs
inimigos para não controlar a frota do jogador.

Não copiar o motor de `DemoBattle` nem criar um segundo resolvedor. Extrair
somente parsing ou apresentação compartilhável quando necessário para evitar
duplicação. As regras de validação continuam nas funções existentes.

A campanha inicial oferece baterias, lances e habilidades com efeitos já
implementados. Torpedos, Nova Cannon, `power_ram`, upgrades/passivas dependentes
de torpedos e as habilidades stub de augur/torpedo ficam indisponíveis, com uma
explicação no catálogo. Aplicar essa restrição também a frotas carregadas e aos
inimigos; não basta esconder opções na interface. Não alterar o catálogo global.

Uma única validação de elegibilidade da campanha deve complementar a validação
de `FleetSpec` na criação, loja, montagem de inimigos e carregamento:

- Armas: somente tipos `BATTERY` e `LANCE`.
- Upgrades: rejeitar `power_ram` e `automated_reload`.
- Habilidades: rejeitar `augur_probe` e `torpedo_barrage`.
- Passivas: rejeitar `short_burn_torpedoes` e `reload_drills`.
- Traits: nenhum adquirido nesta versão; saves desta versão devem ter lista vazia.

Os demais IDs precisam existir no catálogo e passar pelas regras normais de
facção, slots e flagship. `improved_augur_array` continua permitido: aumenta
sensores já implementados, sem depender de sondas. A lista fica em um único
local e é atualizada quando novas mecânicas forem integradas.

Habilidades usam as regras existentes de cargas e cooldown. Exibir quais estão
disponíveis e por que uma ordem foi rejeitada. O fluxo manual deve exercitar
movimento, tiro, stances, abordagem e habilidades já suportadas.

## Estado persistente e montagem da batalha

| Estado | Persistência |
|---|---|
| Campanha | Versão do save, seed, confronto, status, créditos, contador de IDs e facção |
| Nave | ID estável, `ShipSpec`, dano de casco e batalhas sobrevividas |
| Comandante | ID, nome, facção, XP, nível e seleções de habilidades/passivas/traits |
| Flagship | ID estável da nave; índice é calculado apenas ao gerar `FleetSpec` |

`FleetSpec` continua descrevendo equipamento. Um roster da campanha acrescenta
identidade e estado persistente. Nome e posição na lista não identificam uma
nave. IDs novos são exclusivos dentro da campanha e não são reutilizados.

Na montagem, validar o roster, materializar as naves e aplicar o estado
persistente antes de construir as passivas para o primeiro turno. Reutilizar o
comandante da campanha em vez de conservar o starter recriado pela montagem.
Manter um mapeamento explícito de IDs de campanha para IDs de batalha; não
reconstruir esse vínculo por nome ou posição depois de edições no roster.

Entre batalhas, casco danificado e veterania persistem. Escudos, moral,
combustão, subsistemas, incêndios, críticos, postura, cargas e cooldowns são
restaurados para o estado inicial válido; buffs e preparações são descartados.
Essa recuperação de sistemas faz parte do intervalo gratuito nesta versão.
O reparo pago restaura o casco. Persistência de avarias de subsistemas fica
para a expansão das mecânicas da campanha.

Trocar equipamento não repara casco. Guardar dano absoluto: com máximo novo
`M` e dano carregado `D`, o casco disponível é `M - D`. Rejeitar uma alteração
que deixe esse valor menor ou igual a zero até o jogador reparar a nave.

## Loja e evolução da frota

Reutilizar catálogos, cálculo de pontos, validações e operações adequadas do
builder. A campanha mantém o saldo real; `FleetBuilderSession.remaining` não
é a fonte de verdade da economia após a criação da frota.

| Operação | Contrato |
|---|---|
| Comprar nave | Cobrar casco e equipamento selecionados; criar novo ID, casco cheio e crew inicial |
| Trocar arma, upgrade ou doutrina | Cobrar o custo novo e creditar 50% do custo removido, arredondado para baixo por item |
| Remover equipamento | Mesmo reembolso de 50%; validar que a configuração resultante é legal |
| Descartar nave | Sem reembolso nesta versão; mostrar a perda e pedir confirmação na interface |
| Reparar casco | 8 créditos por ponto faltante; reparo integral da nave |
| Reparar todas | Uma transação, aplicada somente se o saldo cobre o total |
| Trocar flagship | Preservar IDs e validar restrições de equipamento exclusivo |

Toda operação é atômica: calcular resultado e custo, validar e só então
alterar o estado. Rejeição preserva roster e créditos. Não permitir combate
sem frota válida e flagship. Naves sobreviventes preservam dano e veterania
ao reequipar; não existe troca de hull em uma nave existente nesta versão.

O nível do comandante progride pelas regras atuais de XP. Seleção de novas
habilidades por nível e restrição de compra por nível ficam para a entrega
de progressão completa; a primeira campanha preserva o loadout inicial.

## Resultado, XP e gravação

O resolvedor já premia XP e veterania na eliminação de uma facção. A campanha
não repete essas premiações. Rendição e limite de turnos encerram a campanha
sem XP adicional. Um fechamento identifica o confronto e só pode ser aplicado
uma vez: copiar sobreviventes/comandante, remover perdas, aplicar recompensa,
avançar confronto ou marcar fim e salvar.

A integração precisa completar a atribuição de destruições no resolvedor:
mortes por habilidades suportadas, como `warp_rift`, devem creditar o comandante
responsável, assim como mortes por armas. Não creditar fogo amigo, nem contar
a mesma nave duas vezes. Mortes por efeitos ambientais sem autoria não geram
crédito individual. A recompensa em créditos usa a diferença entre a frota
inimiga inicial e seus sobreviventes, independentemente da autoria; o bônus
por sobrevivência usa apenas naves do jogador vivas antes de atualizar o roster.

Save JSON versionado, com validação de tipos, limites, IDs únicos, referências,
catálogo suportado, créditos e invariantes do roster. Gravar em arquivo
temporário no mesmo diretório e substituir o destino somente após sucesso.
Arquivo inválido ou versão desconhecida produz erro legível sem substituir
a sessão atual. Erro de gravação mantém a sessão em memória e informa que
a alteração ainda não foi salva; permitir tentar salvar novamente.

Não serializar conexões, event bus ou todo o `GameState`. O save de frota já
existente mantém seu formato; save de campanha é um formato separado.

## Entregas e aceitação

| Entrega | Evidência de conclusão |
|---|---|
| Batalha local manual | Partida aberta pelo menu, com frota personalizada, IA, ordens e habilidade real sem servidor |
| Campanha em memória | Duas batalhas consecutivas com recompensa, reparo, compra, perdas, dano e XP preservados |
| Persistência e encerramento | Continuar do intervalo, concluir cinco vitórias e apresentar derrota sem duplicar prêmios |

Testes comportamentais devem cobrir:

- Controlador com entrada roteirizada, ordens inválidas e habilidade chegando ao resolvedor.
- IA comandando apenas inimigos; seed e ordens iguais reproduzem o confronto.
- Ausência de incremento duplicado de XP/veterania e recompensa aplicada uma vez.
- Crédito de destruição por arma e habilidade, sem crédito por fogo amigo nem duplicação.
- Identidade e flagship corretos após perda, descarte, compra e reequipamento.
- Reequipamento preservando dano e progressão; compra e reparo com saldo insuficiente são atômicos.
- Duas batalhas ligadas por loja e save/load, sem servidor ou espera por entrada interativa.
- Save inválido, versão desconhecida e falha de escrita preservando o estado anterior válido.
- Restrições de equipamento incompleto também aplicadas no carregamento.
- Vitória final, rendição, eliminação simultânea e limite de turnos.

Executar primeiro os testes direcionados e depois os checks exigidos pelo
repositório: Ruff, formatação, mypy e pytest. Registrar falhas preexistentes
separadamente. Fazer também uma partida manual curta; testes não demonstram
sozinhos que a interface ou o balanceamento estão bons.

## Sequência posterior

Após o primeiro ciclo jogável: torpedos e Nova Cannon; abalroamento e sondas;
passivas/upgrades e progressão completos; IA e terreno; campanha estratégica
com mapa, economia e urgência; narrativa, facções e apresentação. Cada entrega
atualiza os cenários da campanha para permitir testar a nova mecânica.
