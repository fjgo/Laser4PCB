import logging
import re
import serial
import time
import serial.tools.list_ports

global _


class GrblCommunicator:
    def __init__(self):
        self.serial_port = None
        self.grbl_ready = False

    @staticmethod
    def get_available_ports():
        ports = serial.tools.list_ports.comports(True)
        return [port.device for port in ports]

    def is_connected(self):
        return self.serial_port is not None and self.serial_port.is_open

    def connect(self, port, baudrate=115200):
        if self.is_connected():
            self.disconnect()
        try:
            self.serial_port = serial.Serial(port, baudrate, timeout=0.1)
            # Despertar a GRBL y asegurarse de que está listo
            self.serial_port.write(b"\r\n\r\n")
            # Esperar a que GRBL se reinicie y envíe el mensaje de bienvenida
            # time.sleep(2)
            self._flush_input_buffer()
            self.grbl_ready = True
            logging.info(("Connected to GRBL on {port}").format(port=port))
            return True
        except serial.SerialException as e:
            logging.error(f"Error connecting to the port {port}: {e}")
            self.grbl_ready = False
            return False

    def disconnect(self):
        if self.is_connected():
            self.serial_port.close()
            logging.info("Disconnected from GRBL")
        self.grbl_ready = False

    def _flush_input_buffer(self):
        # Limpiar cualquier dato de inicio de GRBL
        if self.serial_port:
            while self.serial_port.in_waiting > 0:
                self.serial_port.readline()

    def check_state_ready(self):
        if not self.serial_port or not self.serial_port.is_open or not self.grbl_ready:
            logging.info("Not connected to GRBL or not ready.")
            return False
        return True

    def send_command(self, command):
        if not self.check_state_ready():
            return None
        if not isinstance(command, bytes):
            command = bytes(command.encode())
        command = command.strip() + b"\n"  # GRBL espera un salto de línea al final
        try:
            self.serial_port.write(command)
            response = self.serial_port.readline().decode("utf-8").strip()
            logging.info(f"Sent: {command.strip()} | Received: {response}")
            return response
        except Exception as e:
            logging.error(f"Error al enviar comando: {e}")
            return None

    def stream_gcode_text(self, text):
        if not self.check_state_ready():
            return None
        self._flush_input_buffer()
        for line in text:
            if not self._send_line(line):
                break
        logging.info("Transmisión de G-code completada.")

    def stream_gcode_file(self, filename):
        if not self.check_state_ready():
            return None
        self._flush_input_buffer()
        with open(filename, "r") as f:
            for line in f:
                if not self._send_line(line):
                    break

        logging.info("Transmisión de G-code completada.")

    def _send_line(self, line):
        # Ignorar líneas vacías y comentarios
        line = re.sub(r"\([^)]*\)|;.*$", "", line)
        line = line.strip()
        if not line:
            return True
        response = self.send_command(line)
        time.sleep(0.05)
        # GRBL suele responder con 'ok' o un mensaje de error.
        retries = 0
        while response != "ok":
            if response and "error" in response.lower():
                logging.warning(f"Error GRBL: {response} en línea: {line}")
                return False  # Detener si hay un error
            # Si no es 'ok' o error, espera un poco y lee de nuevo (podría ser un mensaje de estado)
            time.sleep(0.1)
            response = self.serial_port.readline()
            if response == b"":
                if retries == 0:
                    # Si no hay respuesta, intenta enviar un ? para pedir estado
                    self.serial_port.write(b"?\n")
                    time.sleep(0.1)
                    response = self.serial_port.readline().decode("utf-8").strip()
                retries += 1
                print(retries)
            else:
                response = response.decode("utf-8").strip()

            if retries >= 100:
                return False

        return True


if __name__ == "__main__":
    print(GrblCommunicator.get_available_ports())
