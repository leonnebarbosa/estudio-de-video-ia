"""O erro que vira mensagem na pagina. Fica sozinho, sem dependencias, para o instalador (Python minimo) usar o mesmo."""


class Erro(Exception):
    def __init__(self, mensagem, codigo=400):
        super().__init__(mensagem)
        self.mensagem, self.codigo = mensagem, codigo
