# Teste de impressão sem driver
#
# Basicamente, você envia metadados e, depois, vários bitmaps que você deseja encodar
# O bitmap é do tamanho da cabeça de impressão

import time
import socket
from html.parser import HTMLParser
import sys
import math as m
import functools as f

dpi = 360


def pack_byte_encode(bytes):
    """
    Encoda no formato PackByte, um formato de compressão RLE que a impressora usa pra receber

    Basicamente, o formato é assim:
      se a quantidade do byte for <= 128, nós encodamos como <quant-1> <byte>
      se for >= 128, encodamos como <257-quant> <bytes>

    Retorna um buffer encodado como PackByte
    """
    last_byte = None
    last_count = 0
    current_byte = None
    final = []

    def commit_bytes():
        if last_count <= 129:
            final.extend([last_count-1, last_byte])

    for b in bytes:
        current_byte = b
        if current_byte != last_byte and last_byte is not None:
            commit_bytes()
            last_count = 0

        if last_count == 129:
            commit_bytes()
            last_count = 0

        last_byte = current_byte
        last_count += 1

    commit_bytes()
    return final


def identify_printer(addr: str) -> str:
    """
    Identifica a impressora
    Nós acessamos a URL da impressora e verificamos seu nome.

    (Eu queria usar algo do ESC/P pra identificar, mas aparentemente eu não consegui fazer
    a impressora retornar nenhum valor

    Acho que aquele comando de identificação (o ESC \x01) deve ser só pra impressoras
    USB ou algo assim)

    addr é o endereço IP da impressora
    Retorna um nome, ou None se ela não for encontrada
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((addr, 80))

        msg = [
            "GET /PRESENTATION/HTML/TOP/INDEX.HTML HTTP/1.1",
            "Host: 192.168.1.237",
            "User-Agent: printtest/0.1.0"
            "Accept: */*", "", ""]
        bmsg = "\r\n".join(msg).encode("utf-8")
        s.sendall(bmsg)

        res = ""
        while not ("</html>" in res or "</HTML>" in res):
            ares = s.recv(1400)
            if len(ares) == 0:
                break

            res += ares.decode("utf-8")

        [header, body, *_rest] = res.split("\r\n\r\n")
        s.close()

        class MyHTMLParser(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self._can_have_p = False
                self._is_on_p = False
                self.printer_name = None

            def handle_starttag(self, tag, attrs):
                if tag == "body":
                    self._can_have_p = True

                if tag == "p" and self._can_have_p is True and self.printer_name is None:
                    self._is_on_p = True

            def handle_endtag(self, tag):
                if tag == "body":
                    self._can_have_p = False

                if tag == "p" and self._can_have_p is True:
                    self._is_on_p = False

            def handle_data(self, data):
                if self._is_on_p is True:
                    self.printer_name = data

        parser = MyHTMLParser()
        parser.feed(body)

        return parser.printer_name

    except TimeoutError:
        print("Timed out")
        return None

    except Exception as e:
        print(repr(e))
        return None


class TestPrintJob():
    """
    Encapsula o nosso teste de impressão

    Ele gera os bytes para enviar para a impressora
    A impressora vai imprimir, basicamente, 4 linhas: uma preta, uma ciano, uma magenta e uma
    amarela
    """

    def __init__(self, addr, dpi):
        self._dpi = dpi  # 360=normal, 180=rascunho, 720=alta, 1440=altapracaralho
        self._endpoint = (addr, 9100)
        self.buffer = self._fill_header() + self._reset_command()
        self._baseunit = 1440

    def _encode_num_as_bytes(self, val: int, size: int = 1) -> bytes:
        """
        Encoda um número como um array de bytes

        val = o valor
        size = o tamanho, em bytes, do valor (u8=1, u16=2, u32=4)
        """
        num = round(val) if val >= 0 else pow(2, size*8)+round(val)
        if size == 1:
            return bytes([num % 256])
        elif size == 2:
            return bytes([num % 256, num // 256])
        else:  # size == 4
            return bytes([
                num % 256,
                (num // 256) % 256,
                (num // 65536) % 256,
                (num // (65536*256)) % 256
            ])

    def _mm_to_inch(self, val: int) -> int:
        return val*0.0393701

    def _inch_to_mm(self, val: float) -> float:
        return val/0.0393701

    def _mm_to_pageunits(self, val: int, dpi: int, baseunit: int) -> int:
        pageunit = baseunit/dpi
        valinch = self._mm_to_inch(val)
        return m.ceil(valinch / pageunit / (1/baseunit))

    def vunit_to_mm(self, val: float):
        vunit = self._baseunit/self._dpi
        return m.ceil(self._inch_to_mm(val * (vunit/self._baseunit)))


    def advance_vertical(self, unitmm):
        """
        Desce a cabeça de impressão em `unitmm` milimetros

        Na real, o comando é em vunits. Nós tambem convertemos de mm para
        vunits

        (A primeira descida é de 36.576mm, então esse valor deve significar algo)
        """
        vunit = self._baseunit/self._dpi
        pu_advance = m.ceil(self._mm_to_inch(unitmm) / (vunit/self._baseunit))

        return b"\x1b(v\x04\x00" + self._encode_num_as_bytes(pu_advance, 4)

    def move_vertical(self, unitmm):
        """
        Avança a cabeça de impressão `unitmm` milímetros, a partir da margem
        de cima
        """
        vunit = self._baseunit/self._dpi
        pu_advance = m.ceil(self._mm_to_inch(unitmm) / (vunit/self._baseunit))

        return b"\x1b(V\x04\x00" + self._encode_num_as_bytes(pu_advance, 4)

    def move_horizontal(self, unitmm):
        """
        Avança a cabeça de impressão horizontalmente `unitmm` milímetros,
        a partir do começo

        (Isso provavelmente quer dizer que ela volta se estiver depois de
        onde você marcou)

        (A primeira movimentada pro lado é de 16.9333 mm, deve ser algo importante, provavelmente
        a margem)
        """
        hunit = self._baseunit/self._dpi
        pu_advance = m.ceil(self._mm_to_inch(unitmm) / (hunit/self._baseunit))

        return b"\x1b($\x04\x00" + self._encode_num_as_bytes(pu_advance, 4)

    def print_data(self, data, color):
        """
        Imprime alguma coisa, em uma cor de tinta especifica
            0=Preto, 1=Magenta, 2=Ciano, 4=Amarelo

        Os dados estão encodados em bytes

        Geralmente, a impressão é de 2 bits por pixel, 288 bytes/linha
        e 60 linhas

        O driver comprime em PackByte, mas eu vou mandar descomprimido
        pra testar

        bpp são os bits por pixel. Melhor deixar 2
        byte per row é a quantidade de pontos por linha.
        sendo bpp=2 e DPI=360, bytes_per_row=90 pinta o equivalente a 1 polegada.
        lines é a quantidade de linhas a serem pintadas. 45 linhas pintaria o equivalente a meia polegada a 360dpi

        288 é o tamanho de um cabeçote de impressão
        """
        bpp = 2
        byte_per_row = 288
        lines = 60

        bytearr = [self._encode_num_as_bytes(d) for d in data]
        bytedata = f.reduce(lambda acc, v: acc + v, bytearr)

        return b"\x1bi" + self._encode_num_as_bytes(color) + \
            self._encode_num_as_bytes(0) + \
            self._encode_num_as_bytes(bpp) + \
            self._encode_num_as_bytes(byte_per_row, 2) + \
            self._encode_num_as_bytes(lines, 2) + \
            bytedata

    def create_epilogue(self):
        """
        Cria os dados finais do job de impressão

        Os remote modes que tem ai são LD, pra carregar as configs salvas, e JE,
        para terminar o job de impressão

        Sem isso, a impressora não libera a folha
        """
        def _remote_ld():
            return b"LD\x00\x00"

        def _remote_je():
            return b"JE\x01\x00\x00"

        self.buffer += self._reset_command()
        self.buffer += b"\x1b(R\x08\x00\x00REMOTE1" + _remote_ld() + _remote_je() + \
            b"\x1b\x00\x00\x00"

    def end_page(self):
        return b"\x0d\x0c"


    def create_test_page(self):
        from PIL import Image
        from more_itertools import grouper

        import sys
        
        tpj.add_metadata_commands()
        width = 800
        height = 600
#        im = Image.new("RGB", (width, height), (60, 255, 90))
        im = Image.open(sys.argv[1])
#        width, height = im.size
        print(width, height, width, height*4)
        printbuf = im.convert("CMYK").resize((int(width/2), height), Image.BICUBIC)

        # Usually, the printer driver will use some sort of dithering algorithm to
        # increase the color definition of the image;
        
        bwidth = 288
        for yoffset in range(-120, height+240, 60):

            def band(offset, color):
                def colorband(index):
                    return printbuf.crop((bwidth*index, yoffset+offset, bwidth*(index+1),
                                          yoffset+offset+60)).getdata(color)
                return colorband



            cband = band(120, 0)
            mband = band(60, 1) #printbuf.crop((0, yoffset+60, bwidth, yoffset+120)).getdata(1)
            yband = band(0, 2) #printbuf.crop((0, yoffset, bwidth, yoffset+60)).getdata(2)
            kband = band(120, 3) #printbuf.crop((0, yoffset+120, bwidth, yoffset+180)).getdata(3)

            colorbufs = [(0, kband), (2, cband), (1, mband), (4, yband)]

            def colorprint(val):
                return m.floor(val[0]/64) | (m.floor(val[1]/64) << 2) \
                    | (m.floor(val[2]/64) << 4) | (m.floor(val[3]/64) << 6)

            for colorval, bufgen in colorbufs:
                self.buffer += self.move_horizontal(1)
                for idx in range(m.ceil(width/bwidth)):
                    rows = [colorprint([bs, bs, bs, bs]) for bs
                            in bufgen(idx)]
                    self.buffer += self.print_data(rows, colorval)
                    self.buffer += self.move_horizontal(81)

                self.buffer += b"\r"

            self.buffer +=  b"\x1b(v\x04\x00" + self._encode_num_as_bytes(118, 4)

        self.buffer += self.advance_vertical(1)
        self.buffer += self.print_data([0]*288*60, 0)
            

        # As cores que o driver enviou pra impressora, mais ou menos na ordem
        #allcolors = [6, 5, 4, 2, 1, 0]

        # Algumas tintas tem differentes "offsets"
        #
        # As cores 6 (ALTK) e 4 (Y) tem um offset negativo de 240 vunits (sendo 1vunit=4baseunits)
        # As cores 5 (ALTK) e 1 (M) tem offset negativo de 120 vunits.
        # As cores 0 (K) e 2 (C) não tem isso.


        self.buffer += self.end_page()
        self.create_epilogue()

    def add_metadata_commands(self):
        """
        Gera comandos de metadados
        """

        def command_esc_G():
            """
            Ativa o modo gráfico
            """
            return b"\x1b(G\x01\x00\x01"

        def command_esc_U(dpi, baseunit):
            """
            Define unidades de medida
            Elas são pageunits, vunits (pra espaçamento vertical), hunits
            (espaçamento horizontal), baseunit (a unidade padrão)

            Usamos o DPI da impressão pra calcular elas
            """
            pageunits = baseunit/dpi
            vunit = baseunit/dpi
            hunit = baseunit/dpi
            return b"\x1b(U\x05\x00" + self._encode_num_as_bytes(pageunits) \
                + self._encode_num_as_bytes(vunit) \
                + self._encode_num_as_bytes(hunit) \
                + self._encode_num_as_bytes(baseunit, 2) \


        def command_esc_C(pageh):
            """
            Define o tamanho da folha verticalmente

            Recebemos o valor em milimetros, e convertemos pra PAGEUNITS
            """
            pagelen = self._mm_to_pageunits(pageh, self._dpi, self._baseunit)
            return b"\x1b(C\x04\x00" + self._encode_num_as_bytes(pagelen, 4)

        def command_esc_c():
            """
            Define o tamanho da margem

            Até eu descobrir o motivo da margem ser negativa, eu vou usar
            os valores default.
            """
            margintop = -358
            marginlen = 4407

            return b"\x1b(c\x08\x00" + \
                self._encode_num_as_bytes(margintop, 4) + \
                self._encode_num_as_bytes(marginlen, 4)

        def command_esc_S(width, height):
            """
            Define o tamanho da folha (a largura e o comprimento da região a ser
            impressa)
            """
            pu_width = self._mm_to_pageunits(width, self._dpi, self._baseunit)
            pu_height = self._mm_to_pageunits(
                height, self._dpi, self._baseunit)

            return b"\x1b(S\x08\x00" + self._encode_num_as_bytes(pu_width, 4) \
                + self._encode_num_as_bytes(pu_height, 4)

        def command_esc_D(dpi):
            """
            Define o espaçamento vertical e horizontal da impressora

            Provavelmente algo relacionado a cabeça de impressão?
            """
            base = 14400
            nozzle_sep = 4
            vertical = nozzle_sep*base/720
            horizontal = base/dpi

            return b"\x1b(D\x04\x00" + self._encode_num_as_bytes(base, 2) + \
                self._encode_num_as_bytes(vertical) + \
                self._encode_num_as_bytes(horizontal)

        a4width, a4height = 210, 297

        self.buffer += self._fill_remote_mode_commands()

        # ???
        self.buffer += b"\x1b(A\x09\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"

        self.buffer += command_esc_G()
        self.buffer += command_esc_U(self._dpi, self._baseunit)
        self.buffer += b"\x1bU\x00"  # ESC U. Direção da impressão
        # ESC (i. Modo interleave. Não sei o q é
        self.buffer += b"\x1b(i\x01\x00\x00"
        # Copiei o que o driver da l355 manda
        self.buffer += command_esc_C(a4height)
        self.buffer += command_esc_c()
        self.buffer += command_esc_S(a4width, a4height)
        # Usa tinta colorida pra impressoes P/B
        self.buffer += b"\x1b(K\x02\x00\x00\x02"
        # A L355 deixa assim. Deve melhorar a qualidade
        self.buffer += command_esc_D(self._dpi)
        self.buffer += b"\x1b(e\x02\x00\x00\x11"  # Tamanho do ponto.
        # Como ela tem um valor estranho, deixarei assim
        # (Aparentemente 0x11 é o tamanho da gota de tinta: 0x10 é a menor, 0x12 é a maior)

        self.buffer += b"\x1b(m\x01\x00\x20" # ??

        self.buffer += self.advance_vertical(36.576)

    def _fill_remote_mode_commands(self):
        """
        Preenche comandos iniciais de remote mode

        Esses são um dos comandos que configuram a impressora para o job
        Segundo a doc não oficial do gutenprint, eles podem ser omitidos,
        mas nós vamos colocar eles mesmo assim

        O remote mode também pode ser usado pra tarefas de manutenção
        (teste de impressão, limpeza das cabeças de impressão...)

        Iremos colocar o PP (define o caminho do papel, provavelmente a tray)
        """

        def _remote_pp(traynum):
            return b"PP\x03\x00\x00\x01" + self._encode_num_as_bytes(traynum, 1)

        def _remote_pm():
            return b"PM\x02\x00\x00\x00"

        def _unknown_remotes():
            return b"TI\x08\x00\x00\x07\xE5\x05\x16\x05\x2C\x1B" + \
                b"DP\x02\x00\x00\x00SN\x01\x00\x00MI\x04\x00\x00\x01\x00\x00" + \
                b"US\x03\x00\x00\x00\x01US\x03\x00\x00\x01\x00" + \
                b"US\x03\x00\x00\x02\x00US\x03\x00\x00\x05\x00"

        def _remote_fp(inches):
            """
            Define a margem esquerda horizontal
            """
            return b"FP\x03\x00\x00" + self._encode_num_as_bytes(inches*360, 2)

        return b"\x1b(R\x08\x00\x00REMOTE1" + _remote_pm() + \
            _remote_pp(-1) + _unknown_remotes() + _remote_fp(0) + b"\x1b\x00\x00\x00"

    def send_buffer(self):
        """
        Envia o buffer a impressora

        TODO: Tratar erros (ex: papel preso, falta de tinta)
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(self._endpoint)
        s.settimeout(5)

        print("")
        # Divide o buffer em buffers menores pra mandar pra impressora
        d = 2048
        for el in [self.buffer[i:i+d] for i in range(0, len(self.buffer), d)]:
            print(".", end="", flush=True)
            s.sendall(el)
            time.sleep(0.01)

        print("")
        try:
            data = s.recv(2048)
            print("A impressora retornou ", repr(data))
        except socket.timeout as e:
            print("A impressora não retornou nada ")
        finally:
            time.sleep(5)
            s.close()

    def _reset_command(self) -> bytes:
        """
        Gera dados para um comando de reset

        Ele reseta as configs da impressora modificadas pelo job de
        impressão
        """
        return b"\x1b@"

    def _fill_header(self) -> bytes:
        """
        Cria o 'header' da requisição.

        Isso, basicamente, define o início da nossa impressão
        """
        return b"\x00\x00\x00\x1b\x01@EJL 1284.4\n@EJL     \n\x1b@"


arr = [1, 1, 1, 2, 2, 2, 3, 3, 3, 3]
arr.extend(129*[0])
arr.extend(150*[3])

print(repr(pack_byte_encode(arr)))

addr = "127.0.0.1"
#addr = "192.168.1.237"
#name = identify_printer(addr)
#if name is None:
#    print("Printer not found. Please check printer port")
#    print("(Autodetection not yet supported :( )")
#    sys.exit(1)

# print(f"Detected printer '{name}'")

tpj = TestPrintJob(addr, 360)
tpj.create_test_page()

bufsize = len(tpj.buffer)
print(f"Buffer gerado ({bufsize} bytes)")
print("Hora da verdade!")

tpj.send_buffer()
print("Vai lá ver se deu certo! É pra imprimir uma linha de cada cor.")
