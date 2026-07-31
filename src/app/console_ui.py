"""Technical console interface for operators."""

from __future__ import annotations

import asyncio
import queue
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import PureWindowsPath
from typing import Callable, TypeVar

from src.app.floating_marker import FloatingMarkerWindow
from src.app.session_controller import SessionController
from src.audio.audio_models import AudioDirection
from src.audio.device_enumerator import collect_audio_inventory
from src.audio.microphone_tester import run_microphone_test
from src.audio.output_tester import run_output_test
from src.monitoring.process_snapshot import ProcessInfo, ProcessSnapshotService
from src.storage.models import (
    CustomerMarkSignal,
    MonitoringRequest,
    MonitoringSession,
    MonitoringSnapshot,
    ProbeStatus,
)
from src.utils.config_loader import AppConfig
from src.utils.profile_loader import MonitoringProfile, load_profiles
from src.utils.time_utils import format_datetime_local, format_datetime_local_ms, format_seconds
from src.utils.validators import parse_positive_float, parse_positive_int
from src.utils.windows_handlers import SignalGuard

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
except ImportError:  # pragma: no cover - fallback for minimal environments
    Console = None  # type: ignore[assignment]
    Group = None  # type: ignore[assignment]
    Live = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Prompt = None  # type: ignore[assignment]
    Confirm = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]

T = TypeVar("T")


def _raise_value_error(message: str) -> None:
    raise ValueError(message)


class ConsoleUI:
    """Rich-powered console used by the support team."""

    def __init__(self, controller: SessionController, app_config: AppConfig) -> None:
        self._controller = controller
        self._config = app_config
        self._console = Console() if Console else None

    def run(self) -> int:
        """Run the main operator menu."""
        self._show_header()
        incomplete = self._controller.list_incomplete_sessions()
        if incomplete:
            self._show_incomplete_sessions(incomplete)

        while True:
            self._show_menu()
            option = self._ask("Opcao", default="1").strip()
            if option == "1":
                request = self._collect_monitoring_request()
                try:
                    session = self._controller.start_session(request)
                except ValueError as exc:
                    self._print(str(exc), style="red")
                    continue
                self._show_session_started(session)
                self._run_monitoring_session(session)
            elif option == "2":
                self._show_config()
            elif option == "3":
                self._recover_incomplete_session()
            elif option == "4":
                self._audio_tools_menu()
            elif option == "5":
                if self._confirm_exit():
                    return 0
            else:
                self._print("Opcao invalida.", style="red")

    def _show_header(self) -> None:
        title = f"{self._config.app.name} v{self._config.app.version}"
        subtitle = "Console tecnico de monitoramento"
        if self._console and Panel:
            self._console.print(Panel.fit(subtitle, title=title, border_style="cyan"))
        else:
            print(f"{title}\n{subtitle}")

    def _show_menu(self) -> None:
        if self._console and Table:
            table = Table(title="Menu principal", show_header=True, header_style="bold cyan")
            table.add_column("Opcao", width=8)
            table.add_column("Acao")
            table.add_row("1", "Iniciar novo monitoramento")
            table.add_row("2", "Visualizar configuracoes")
            table.add_row("3", "Consultar sessoes incompletas")
            table.add_row("4", "Ferramentas de audio")
            table.add_row("5", "Sair")
            self._console.print(table)
        else:
            print("1 - Iniciar novo monitoramento")
            print("2 - Visualizar configuracoes")
            print("3 - Consultar sessoes incompletas")
            print("4 - Ferramentas de audio")
            print("5 - Sair")

    def _audio_tools_menu(self) -> None:
        while True:
            if self._console and Table:
                table = Table(title="Ferramentas de audio", show_header=True, header_style="bold cyan")
                table.add_column("Opcao", width=8)
                table.add_column("Acao")
                table.add_row("1", "Listar dispositivos")
                table.add_row("2", "Atualizar inventario")
                table.add_row("3", "Testar microfone")
                table.add_row("4", "Testar reproducao")
                table.add_row("5", "Voltar")
                self._console.print(table)
            else:
                print("1 - Listar dispositivos")
                print("2 - Atualizar inventario")
                print("3 - Testar microfone")
                print("4 - Testar reproducao")
                print("5 - Voltar")
            option = self._ask("Opcao", default="1").strip()
            if option in {"1", "2"}:
                self._show_audio_inventory()
            elif option == "3":
                self._run_microphone_tool()
            elif option == "4":
                self._run_output_tool()
            elif option == "5":
                return
            else:
                self._print("Opcao invalida.", style="red")

    def _show_audio_inventory(self) -> None:
        inventory = collect_audio_inventory()
        if self._console and Table:
            table = Table(title="Inventario de audio", show_header=True, header_style="bold cyan")
            table.add_column("Tipo")
            table.add_column("Dispositivo")
            table.add_column("Estado")
            table.add_column("Padrao")
            table.add_column("Comunicacao")
            table.add_column("Conexao")
            for device in inventory.devices:
                table.add_row(
                    device.direction.value,
                    device.name,
                    device.state.value,
                    "sim" if device.is_default else "nao",
                    "sim" if device.is_default_communications else "nao",
                    device.connection_type or "N/D",
                )
            self._console.print(table)
        else:
            for device in inventory.devices:
                print(f"{device.direction.value}: {device.name} ({device.state.value})")
        for error in inventory.errors or []:
            self._print(f"Audio N/D: {error}", style="yellow")

    def _run_microphone_tool(self) -> None:
        inventory = collect_audio_inventory(include_driver_info=False)
        inputs = [device for device in inventory.devices if device.direction == AudioDirection.INPUT]
        if not inputs:
            self._print("Nenhum dispositivo de entrada disponivel para teste.", style="yellow")
            return
        self._print("Este teste mede apenas niveis tecnicos do microfone. O audio nao sera salvo.", style="cyan")
        device = self._choose_audio_device(inputs)
        self._print("Fale normalmente durante cinco segundos.", style="cyan")
        result = run_microphone_test(
            device.stable_id,
            duration_seconds=self._config.monitoring.microphone_test_duration_seconds,
        )
        self._show_key_values(
            "Resultado do teste de microfone",
            {
                "Dispositivo": result.device_name or device.name,
                "Estado": result.state.value,
                "Sinal": result.signal_detected,
                "RMS": result.rms,
                "Pico": result.peak,
                "Silencio": result.silence_percent,
                "Erro": result.error,
            },
        )

    def _run_output_tool(self) -> None:
        inventory = collect_audio_inventory(include_driver_info=False)
        outputs = [device for device in inventory.devices if device.direction == AudioDirection.OUTPUT]
        if not outputs:
            self._print("Nenhum dispositivo de saida disponivel para teste.", style="yellow")
            return
        device = self._choose_audio_device(outputs)
        result = run_output_test(device.stable_id, channel="stereo")
        confirmation = self._ask(
            "Confirmacao (OUVI CORRETAMENTE/NAO OUVI/OUVI APENAS O CANAL ESQUERDO/OUVI APENAS O CANAL DIREITO/SOM MUITO BAIXO/SOM DISTORCIDO)",
            default="OUVI CORRETAMENTE",
        )
        result = replace(result, user_confirmation=confirmation, result=self._output_confirmation_result(result.stream_accepted, confirmation))
        self._show_key_values(
            "Resultado do teste de reproducao",
            {
                "Dispositivo": result.device_name or device.name,
                "Fluxo aceito": result.stream_accepted,
                "Confirmacao": result.user_confirmation,
                "Resultado": result.result,
                "Erro": result.error,
            },
        )

    @staticmethod
    def _output_confirmation_result(stream_accepted: bool, confirmation: str) -> str:
        if not stream_accepted:
            return "FALHA TECNICA NA REPRODUCAO"
        if confirmation == "OUVI CORRETAMENTE":
            return "REPRODUCAO CONFIRMADA PELO USUARIO"
        return "REPRODUCAO ACEITA PELO WINDOWS, MAS USUARIO RELATOU PROBLEMA"

    def _choose_audio_device(self, devices: list[object]) -> object:
        if self._console and Table:
            table = Table(title="Selecione o dispositivo", show_header=True)
            table.add_column("Opcao")
            table.add_column("Dispositivo")
            for index, device in enumerate(devices, start=1):
                table.add_row(str(index), device.name)
            self._console.print(table)
        selected = self._ask_until_valid(
            "Dispositivo",
            lambda value: devices[int(value) - 1] if 1 <= int(value) <= len(devices) else (_raise_value_error("Dispositivo invalido.")),
            default="1",
        )
        return selected

    def _show_key_values(self, title: str, values: dict[str, object]) -> None:
        if self._console and Table:
            table = Table(title=title, show_header=False)
            table.add_column("Campo")
            table.add_column("Valor")
            for key, value in values.items():
                table.add_row(str(key), str(value if value not in (None, "") else "N/D"))
            self._console.print(table)
        else:
            print(title)
            for key, value in values.items():
                print(f"{key}: {value if value not in (None, '') else 'N/D'}")

    def _collect_monitoring_request(self) -> MonitoringRequest:
        default_duration = str(self._config.monitoring.default_duration_minutes)
        default_interval = str(self._config.monitoring.default_interval_seconds)
        default_sip_port = str(self._config.monitoring.default_sip_port)
        profiles = load_profiles()
        selected_profile = self._choose_profile(profiles)

        client_name = self._ask_required("Nome do cliente")
        unit = self._ask("Unidade/identificacao opcional", default="")
        problem = self._ask_required("Descricao do problema")
        duration = self._ask_until_valid(
            "Duracao em minutos",
            lambda value: parse_positive_int(value, field_name="duracao"),
            default=default_duration,
        )
        interval = self._ask_until_valid(
            "Intervalo de coleta em segundos",
            lambda value: parse_positive_float(value, field_name="intervalo"),
            default=default_interval,
        )
        sip_target = self._ask_required("Dominio ou IP do servidor SIP", default=self._config.monitoring.default_sip_target)
        sip_port = self._ask_until_valid(
            "Porta do servico",
            lambda value: parse_positive_int(value, field_name="porta"),
            default=default_sip_port,
        )
        protocol = self._ask_required("Protocolo esperado", default=self._config.monitoring.default_protocol)
        external_target = self._ask("Destino externo adicional", default=self._config.monitoring.default_external_target)
        notes = self._ask("Observacoes do suporte", default="")
        softphone = self._collect_softphone_selection()

        return MonitoringRequest(
            client_name=client_name,
            unit=unit,
            problem_description=problem,
            duration_minutes=duration,
            collection_interval_seconds=interval,
            sip_target=sip_target,
            service_port=sip_port,
            expected_protocol=protocol,
            external_target=external_target,
            support_notes=notes,
            profile_id=selected_profile.profile_id,
            softphone_monitor_enabled=bool(softphone["enabled"]),
            softphone_process_name=str(softphone["process_name"]),
            softphone_expected_path=str(softphone["expected_path"]),
            softphone_expected_pid=softphone["expected_pid"],
        )

    def _collect_softphone_selection(self) -> dict[str, object]:
        if not self._config.monitoring.softphone_monitor_enabled:
            return {"enabled": False, "process_name": "", "expected_path": "", "expected_pid": None}
        enabled = self._ask("Monitorar processo do softphone? (s/n)", default="s").strip().lower()
        if enabled not in {"s", "sim", "y", "yes"}:
            return {"enabled": False, "process_name": "", "expected_path": "", "expected_pid": None}
        mode = self._ask("Softphone: 1 selecionar processo aberto, 2 informar manualmente", default="1").strip()
        if mode == "1":
            selected = self._select_running_process()
            if selected:
                return {
                    "enabled": True,
                    "process_name": selected.name,
                    "expected_path": selected.exe or "",
                    "expected_pid": selected.pid,
                }
        process_name = self._ask("Nome do executavel do softphone", default="").strip()
        expected_path = self._ask("Caminho esperado opcional", default="").strip()
        process_name, expected_path = self._normalize_manual_softphone(process_name, expected_path)
        if not process_name and not expected_path:
            self._print("Softphone nao informado; monitoramento do processo sera desabilitado.", style="yellow")
            return {"enabled": False, "process_name": "", "expected_path": "", "expected_pid": None}
        return {
            "enabled": True,
            "process_name": process_name,
            "expected_path": expected_path,
            "expected_pid": None,
        }

    def _select_running_process(self) -> ProcessInfo | None:
        choices = ProcessSnapshotService(ttl_seconds=0.0).process_choices(limit=50, visible_apps_only=True)
        if not choices:
            self._print("Nenhum aplicativo com janela visivel foi encontrado; informe manualmente.", style="yellow")
            return None
        if self._console and Table:
            table = Table(title="Aplicativos abertos", show_header=True, header_style="bold cyan")
            table.add_column("Opcao", width=8)
            table.add_column("PID", justify="right")
            table.add_column("Processo")
            table.add_column("Janela", overflow="ellipsis")
            table.add_column("Caminho", overflow="ellipsis")
            for index, process in enumerate(choices, start=1):
                table.add_row(
                    str(index),
                    str(process.pid),
                    process.name,
                    process.window_title or "N/D",
                    process.exe or "N/D",
                )
            self._console.print(table)
        selected = self._ask_until_valid(
            "Processo",
            lambda value: choices[int(value) - 1] if 1 <= int(value) <= len(choices) else (_raise_value_error("Processo invalido.")),
            default="1",
        )
        return selected

    @staticmethod
    def _normalize_manual_softphone(process_name: str, expected_path: str) -> tuple[str, str]:
        process_name = process_name.strip().strip('"')
        expected_path = expected_path.strip().strip('"')
        if process_name and ("\\" in process_name or "/" in process_name):
            expected_path = expected_path or process_name
            process_name = PureWindowsPath(process_name).name
        elif expected_path and not process_name:
            process_name = PureWindowsPath(expected_path).name
        if process_name and "." not in PureWindowsPath(process_name).name:
            process_name = f"{process_name}.exe"
        return process_name, expected_path

    def _choose_profile(self, profiles: list[MonitoringProfile]) -> MonitoringProfile:
        if not profiles:
            raise ValueError("Nenhum perfil de monitoramento encontrado.")
        if self._console and Table:
            table = Table(title="Perfis de monitoramento", show_header=True, header_style="bold cyan")
            table.add_column("Opcao", width=8)
            table.add_column("Perfil")
            table.add_column("Foco")
            for index, profile in enumerate(profiles, start=1):
                table.add_row(str(index), profile.name, profile.description)
            self._console.print(table)
        else:
            for index, profile in enumerate(profiles, start=1):
                print(f"{index} - {profile.name}: {profile.description}")
        selected = self._ask_until_valid(
            "Perfil",
            lambda value: self._parse_profile_choice(value, profiles),
            default=str(len(profiles)),
        )
        return selected

    @staticmethod
    def _parse_profile_choice(value: str, profiles: list[MonitoringProfile]) -> MonitoringProfile:
        try:
            index = int(value)
        except ValueError as exc:
            raise ValueError("Perfil deve ser uma opcao numerica.") from exc
        if not 1 <= index <= len(profiles):
            raise ValueError("Perfil informado nao existe.")
        return profiles[index - 1]

    def _show_session_started(self, session: MonitoringSession) -> None:
        if self._console and Table:
            table = Table(title="Monitoramento preparado", show_header=False)
            table.add_column("Campo")
            table.add_column("Valor")
            table.add_row("Sessao", session.session_id)
            table.add_row("Cliente", session.request.client_name)
            table.add_row("Perfil", session.request.profile_id)
            table.add_row("Status", session.status)
            table.add_row("Inicio", format_datetime_local(session.started_at))
            table.add_row("Termino previsto", format_datetime_local(session.expected_end_at))
            self._console.print(table)
        else:
            print(f"Sessao {session.session_id} iniciada para {session.request.client_name}.")
        self._print("Sessao criada e persistida em SQLite.", style="green")
        self._print("Iniciando botao flutuante e contexto de marcacoes.", style="cyan")

    def _run_monitoring_session(self, session: MonitoringSession) -> None:
        mark_queue: queue.Queue[CustomerMarkSignal] = queue.Queue(maxsize=100)
        marker = FloatingMarkerWindow(
            mark_queue,
            debounce_seconds=self._config.monitoring.marker_debounce_seconds,
        )
        marker_started = marker.start()
        if not marker_started:
            self._print("Botao flutuante indisponivel; monitoramento seguira sem marcacoes do cliente.", style="yellow")
        signal_guard = SignalGuard(
            lambda source: self._record_close_attempt(session.session_id, source)
        )
        signal_guard.install()

        try:
            if self._console and Live and Panel:
                placeholder = Panel.fit("Preparando monitores...", title="Monitoramento ativo")
                with Live(placeholder, console=self._console, refresh_per_second=2) as live:

                    def update(snapshot: MonitoringSnapshot) -> None:
                        live.update(self._render_monitoring_dashboard(snapshot))

                    try:
                        final_snapshot = asyncio.run(
                            self._controller.run_monitoring(
                                session,
                                on_snapshot=update,
                                mark_queue=mark_queue,
                            )
                        )
                    except KeyboardInterrupt:
                        self._controller.finish_session(session.session_id, interrupted=True)
                        self._print("Monitoramento interrompido pelo operador.", style="yellow")
                        return
                    live.update(self._render_monitoring_dashboard(final_snapshot))
            else:
                try:
                    asyncio.run(
                        self._controller.run_monitoring(
                            session,
                            on_snapshot=self._print_snapshot_line,
                            mark_queue=mark_queue,
                        )
                    )
                except KeyboardInterrupt:
                    self._controller.finish_session(session.session_id, interrupted=True)
                    self._print("Monitoramento interrompido pelo operador.")
                    return
        finally:
            signal_guard.restore()
            marker.stop()
        self._print("Monitoramento finalizado e medicoes gravadas em SQLite.", style="green")
        try:
            zip_path = self._controller.generate_report_for_session(session.session_id)
        except Exception as exc:
            self._print(f"Falha ao gerar relatorio: {exc}", style="red")
            return
        self._print(f"Relatorio gerado: {zip_path}", style="green")

    def _record_close_attempt(self, session_id: str, source: str) -> None:
        self._print(f"Monitoramento em andamento. {source} registrado e ignorado.", style="yellow")
        self._controller.record_close_attempt(session_id, source)

    def _render_monitoring_dashboard(self, snapshot: MonitoringSnapshot) -> object:
        if not (Table and Panel and Group):
            return "Monitoramento ativo"

        status_table = Table.grid(padding=(0, 2))
        status_table.add_column(style="cyan")
        status_table.add_column()
        status_table.add_row("Cliente", snapshot.session.request.client_name)
        status_table.add_row("Problema", snapshot.session.request.problem_description)
        status_table.add_row("Tempo decorrido", format_seconds(snapshot.elapsed_seconds))
        status_table.add_row("Tempo restante", format_seconds(snapshot.remaining_seconds))
        if snapshot.is_warmup:
            status_table.add_row("Fase", f"AQUECENDO ({snapshot.warmup_remaining_seconds}s restantes)")
            status_table.add_row("Diagnostico", "Medicoes iniciais salvas, fora do resumo oficial")
        else:
            status_table.add_row("Fase", "MONITORAMENTO OFICIAL")
        status_table.add_row("Gateway", snapshot.gateway_host or "indisponivel")
        status_table.add_row("Interface", snapshot.active_interface or "indisponivel")
        status_table.add_row("Conexao", snapshot.connection_type or "indisponivel")
        status_table.add_row("Marcacoes do cliente", str(snapshot.customer_mark_count))
        if snapshot.latest_customer_mark_at:
            status_table.add_row("Ultima marcacao", format_datetime_local_ms(snapshot.latest_customer_mark_at))

        summary_table = Table(title="Resumo principal", expand=True)
        summary_table.add_column("Area", no_wrap=True, overflow="ellipsis")
        summary_table.add_column("Estado", width=14, no_wrap=True)
        summary_table.add_column("Atual", justify="right", width=12, no_wrap=True)
        summary_table.add_column("Resumo", overflow="ellipsis")
        for status in (snapshot.group_statuses or {}).values():
            summary_table.add_row(
                status.name,
                self._status_label(status.status),
                self._format_ms(status.latency_ms),
                status.summary,
            )

        diagnostics_table = Table(title="Diagnosticos rapidos", expand=True)
        diagnostics_table.add_column("Item", no_wrap=True, overflow="ellipsis")
        diagnostics_table.add_column("Valor", no_wrap=True, overflow="ellipsis")
        diagnostics = snapshot.diagnostics or {}
        traffic = diagnostics.get("traffic") or {}
        system = diagnostics.get("system") or {}
        wifi = diagnostics.get("wifi") or {}
        sip_options = diagnostics.get("sip_options") or {}
        public_ip = diagnostics.get("public_ip") or {}
        voice = diagnostics.get("voice_quality") or {}
        audio = diagnostics.get("audio") or {}
        softphone = diagnostics.get("softphone") or {}
        softphone_selected = softphone.get("selected") if isinstance(softphone.get("selected"), dict) else {}
        diagnostics_table.add_row("Qualidade de voz", str(voice.get("state", "nao disponivel")))
        diagnostics_table.add_row("Upload atual", self._format_mbps(traffic.get("upload_mbps")))
        diagnostics_table.add_row("Download atual", self._format_mbps(traffic.get("download_mbps")))
        diagnostics_table.add_row("CPU", self._format_percent(system.get("cpu_percent")))
        diagnostics_table.add_row("Memoria", self._format_percent(system.get("memory_used_percent")))
        diagnostics_table.add_row("Sinal Wi-Fi", self._format_percent(wifi.get("signal_percent")))
        diagnostics_table.add_row("SIP OPTIONS", self._sip_options_label(sip_options))
        diagnostics_table.add_row("IP publico", str(public_ip.get("ipv4") or public_ip.get("ipv6") or "nao disponivel"))
        diagnostics_table.add_row("Audio entrada", str(audio.get("default_input") or "nao disponivel"))
        diagnostics_table.add_row("Audio saida", str(audio.get("default_output") or "nao disponivel"))
        diagnostics_table.add_row("Audio erros driver", str(audio.get("driver_error_count", "nao disponivel")))
        diagnostics_table.add_row("Softphone", str(softphone_selected.get("name") or "nao configurado/nao encontrado"))
        diagnostics_table.add_row("Softphone PID", str(softphone_selected.get("pid") or "nao disponivel"))

        results_table = Table(title="Ultimos resultados", expand=True)
        results_table.add_column("Destino", no_wrap=True, overflow="ellipsis")
        results_table.add_column("Tipo", width=10, no_wrap=True)
        results_table.add_column("Estado", width=14, no_wrap=True)
        results_table.add_column("Atual", justify="right", width=12, no_wrap=True)
        results_table.add_column("Info", overflow="ellipsis")
        for result in snapshot.latest_results:
            results_table.add_row(
                result.target.name,
                result.target.kind.value,
                self._status_label(result.status),
                self._format_ms(result.latency_ms),
                result.error or "",
            )

        metrics_table = Table(title="Metricas oficiais acumuladas", expand=True)
        metrics_table.add_column("Destino", no_wrap=True, overflow="ellipsis")
        metrics_table.add_column("Testes", justify="right")
        metrics_table.add_column("Perda", justify="right")
        metrics_table.add_column("Media", justify="right")
        metrics_table.add_column("P95", justify="right")
        metrics_table.add_column("Pico", justify="right")
        metrics_table.add_column("Jitter", justify="right")
        metrics_table.add_column("Falhas seg.", justify="right")
        metrics_table.add_column("Disp.", justify="right")
        metrics_table.add_column("Ult. falha", justify="right", overflow="ellipsis")
        for summary in snapshot.metrics:
            metrics_table.add_row(
                summary.target_name,
                str(summary.tests),
                f"{summary.packet_loss_percent:.1f}%",
                self._format_ms(summary.latency_avg_ms),
                self._format_ms(summary.latency_p95_ms),
                self._format_ms(summary.latency_max_ms),
                self._format_ms(summary.jitter_ms),
                str(summary.consecutive_failures),
                f"{summary.availability_percent:.2f}%",
                format_datetime_local(summary.last_failure_at) if summary.last_failure_at else "-",
            )

        events_table = Table(title="Linha do tempo recente", expand=True)
        events_table.add_column("Horario", width=20, no_wrap=True)
        events_table.add_column("Sev.", width=12, no_wrap=True)
        events_table.add_column("Evento", overflow="ellipsis")
        events_table.add_column("Mensagem", overflow="ellipsis")
        for event in snapshot.timeline_events or []:
            events_table.add_row(
                format_datetime_local_ms(event.occurred_at),
                event.severity.value.upper(),
                event.event_type,
                event.message,
            )

        return Group(
            Panel(status_table, title=f"{self._config.app.name} v{self._config.app.version}", border_style="cyan"),
            summary_table,
            diagnostics_table,
            results_table,
            metrics_table,
            events_table,
        )

    def _print_snapshot_line(self, snapshot: MonitoringSnapshot) -> None:
        summary = ", ".join(
            f"{item.target.name}={item.status.value}/{self._format_ms(item.latency_ms)}"
            for item in snapshot.latest_results
        )
        self._print(
            f"{format_seconds(snapshot.elapsed_seconds)} restante {format_seconds(snapshot.remaining_seconds)} "
            f"| marcacoes {snapshot.customer_mark_count} | {summary}"
        )

    @staticmethod
    def _format_ms(value: float | None) -> str:
        return "-" if value is None else f"{value:.0f} ms"

    @staticmethod
    def _format_mbps(value: object) -> str:
        return "nao disponivel" if value is None else f"{float(value):.1f} Mbps"

    @staticmethod
    def _format_percent(value: object) -> str:
        return "nao disponivel" if value is None else f"{float(value):.0f}%"

    @staticmethod
    def _sip_options_label(payload: dict[str, object]) -> str:
        if not payload:
            return "nao disponivel"
        code = payload.get("sip_code")
        reason = payload.get("sip_reason")
        status = payload.get("status")
        if code:
            return f"{code} {reason or ''}".strip()
        return str(status or "nao disponivel")

    @staticmethod
    def _status_label(status: ProbeStatus) -> str:
        if status == ProbeStatus.ONLINE:
            return "[green]ONLINE[/green]"
        if status == ProbeStatus.DEGRADED:
            return "[yellow]DEGRADADO[/yellow]"
        if status == ProbeStatus.OFFLINE:
            return "[red]OFFLINE[/red]"
        if status == ProbeStatus.INCONCLUSIVE:
            return "[cyan]INCONCLUSIVO[/cyan]"
        if status == ProbeStatus.WARMING_UP:
            return "[cyan]AQUECENDO[/cyan]"
        return "[white]DESCONHECIDO[/white]"

    def _show_config(self) -> None:
        config_map = asdict(self._config)
        for section, values in config_map.items():
            self._print(f"[{section}]", style="cyan")
            for key, value in values.items():
                self._print(f"{key}: {value}")

    def _show_incomplete_sessions(self, sessions: list[MonitoringSession]) -> None:
        if not sessions:
            self._print("Nenhuma sessao incompleta encontrada.", style="green")
            return
        if self._console and Table:
            table = Table(title="Sessoes incompletas")
            table.add_column("ID", overflow="ellipsis")
            table.add_column("Cliente", overflow="ellipsis")
            table.add_column("Inicio")
            table.add_column("Ultimo registro")
            table.add_column("Medicoes", justify="right")
            table.add_column("Marcacoes", justify="right")
            table.add_column("Ultimo estado")
            for session in sessions:
                stats = self._controller.session_recovery_stats(session.session_id)
                table.add_row(
                    session.session_id,
                    session.request.client_name,
                    format_datetime_local(session.started_at),
                    self._format_optional_iso_datetime(stats.get("last_measurement_at")),
                    str(stats.get("measurement_count", 0)),
                    str(stats.get("mark_count", 0)),
                    str(stats.get("last_status") or "desconhecido"),
                )
            self._console.print(table)
        else:
            for session in sessions:
                print(f"{session.session_id} - {session.request.client_name} - {session.status}")

    def _recover_incomplete_session(self) -> None:
        sessions = self._controller.list_incomplete_sessions()
        self._show_incomplete_sessions(sessions)
        if not sessions:
            return
        session_id = self._ask("ID para gerar relatorio parcial ou vazio para voltar", default="")
        if not session_id:
            return
        self._print("1 - Gerar relatorio parcial")
        self._print("2 - Arquivar sessao")
        self._print("3 - Ignorar por enquanto")
        self._print("4 - Excluir sessao")
        action = self._ask("Opcao de recuperacao", default="1")
        if action == "1":
            try:
                zip_path = self._controller.generate_report_for_session(session_id, interrupted=True)
            except ValueError as exc:
                self._print(str(exc), style="red")
                return
            self._print(f"Relatorio parcial gerado: {zip_path}", style="green")
        elif action == "2":
            self._controller.archive_session(session_id)
            self._print("Sessao arquivada.", style="green")
        elif action == "3":
            self._print("Sessao mantida para recuperacao futura.", style="cyan")
        elif action == "4":
            confirmation = self._ask("Digite EXCLUIR para confirmar", default="")
            if confirmation == "EXCLUIR":
                self._controller.delete_session(session_id)
                self._print("Sessao excluida.", style="yellow")
            else:
                self._print("Exclusao cancelada.", style="cyan")
        else:
            self._print("Opcao invalida.", style="red")

    @staticmethod
    def _format_optional_iso_datetime(value: object) -> str:
        if not value:
            return "sem registro"
        try:
            return format_datetime_local(datetime.fromisoformat(str(value)))
        except ValueError:
            return str(value)

    def _ask(self, label: str, default: str | None = None) -> str:
        if self._console and Prompt:
            value = Prompt.ask(label, default=default)
            return "" if value is None else str(value)
        suffix = f" [{default}]" if default is not None else ""
        value = input(f"{label}{suffix}: ").strip()
        return value if value else (default or "")

    def _ask_until_valid(self, label: str, parser: Callable[[str], T], default: str) -> T:
        while True:
            raw = self._ask(label, default=default)
            try:
                return parser(raw)
            except ValueError as exc:
                self._print(str(exc), style="red")

    def _ask_required(self, label: str, default: str | None = None) -> str:
        while True:
            value = self._ask(label, default=default).strip()
            if value:
                return value
            self._print(f"{label} e obrigatorio.", style="red")

    def _confirm_exit(self) -> bool:
        if self._console and Confirm:
            return Confirm.ask("Sair antes de iniciar monitoramento?", default=True)
        answer = input("Sair antes de iniciar monitoramento? [s/N]: ").strip().lower()
        return answer in {"s", "sim", "y", "yes"}

    def _print(self, message: str, style: str | None = None) -> None:
        if self._console:
            self._console.print(message, style=style)
        else:
            print(message)


def utc_now() -> datetime:
    """Return current UTC time for UI-adjacent diagnostics."""
    return datetime.now(UTC)
