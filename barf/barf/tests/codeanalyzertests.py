import unittest
import networkx

from barf.analysis.basicblock.basicblock import BasicBlock
from barf.analysis.basicblock.basicblock import BasicBlockBuilder
from barf.analysis.basicblock.basicblock import BasicBlockGraph
from barf.analysis.codeanalyzer.codeanalyzer import CodeAnalyzer
from barf.analysis.codeanalyzer.codeanalyzer import GenericContext
from barf.analysis.codeanalyzer.codeanalyzer import GenericFlag
from barf.analysis.codeanalyzer.codeanalyzer import GenericRegister
from barf.arch import ARCH_X86_MODE_32
from barf.arch.x86.x86base import X86ArchitectureInformation
from barf.arch.x86.x86disassembler import X86Disassembler
from barf.arch.x86.x86translator import X86Translator
from barf.core.bi import Memory
from barf.core.smt.smtlibv2 import Z3Solver as SmtSolver
from barf.core.smt.smttranslator import SmtTranslator

verbose = False

class MemoryMock(Memory):

    def __init__(self):
        super(MemoryMock, self).__init__(self._read_function, \
            self._write_function)

    def set_base_address(self, address):
        self._base_address = address

    def set_content(self, content):
        self._content = content

    def _read_function(self, address, size):
        start = address - self._base_address
        end = (address + size) - self._base_address

        return self._content[start:end]

    def _write_function(self, address, size):
        pass


class CodeAnalyzerTests(unittest.TestCase):

    def setUp(self):
        self._arch_info = X86ArchitectureInformation(ARCH_X86_MODE_32)
        self._operand_size = self._arch_info.operand_size
        self._memory = MemoryMock()
        self._smt_solver = SmtSolver()
        self._smt_translator = SmtTranslator(self._smt_solver, self._operand_size)
        self._smt_translator.set_reg_access_mapper(self._arch_info.register_access_mapper())
        self._smt_translator.set_arch_registers_size(self._arch_info.register_size)
        self._disasm = X86Disassembler()
        self._ir_translator = X86Translator()
        self._bb_builder = BasicBlockBuilder(self._disasm, self._memory, self._ir_translator)

    def test_check_path_satisfiability(self):
        if verbose:
            print "[+] Test: test_check_path_satisfiability"

        # binary : stack1
        bin_start_address, bin_end_address = 0x08048ec0, 0x8048f02

        binary  = "\x55"                          # 0x08048ec0 : push   ebp
        binary += "\x89\xe5"                      # 0x08048ec1 : mov    ebp,esp
        binary += "\x83\xec\x60"                  # 0x08048ec3 : sub    esp,0x60
        binary += "\x8d\x45\xfc"                  # 0x08048ec6 : lea    eax,[ebp-0x4]
        binary += "\x89\x44\x24\x08"              # 0x08048ec9 : mov    DWORD PTR [esp+0x8],eax
        binary += "\x8d\x45\xac"                  # 0x08048ecd : lea    eax,[ebp-0x54]
        binary += "\x89\x44\x24\x04"              # 0x08048ed0 : mov    DWORD PTR [esp+0x4],eax
        binary += "\xc7\x04\x24\xa8\x5a\x0c\x08"  # 0x08048ed4 : mov    DWORD PTR [esp],0x80c5aa8
        binary += "\xe8\xa0\x0a\x00\x00"          # 0x08048edb : call   8049980 <_IO_printf>
        binary += "\x8d\x45\xac"                  # 0x08048ee0 : lea    eax,[ebp-0x54]
        binary += "\x89\x04\x24"                  # 0x08048ee3 : mov    DWORD PTR [esp],eax
        binary += "\xe8\xc5\x0a\x00\x00"          # 0x08048ee6 : call   80499b0 <_IO_gets>
        binary += "\x8b\x45\xfc"                  # 0x08048eeb : mov    eax,DWORD PTR [ebp-0x4]
        binary += "\x3d\x44\x43\x42\x41"          # 0x08048eee : cmp    eax,0x41424344
        binary += "\x75\x0c"                      # 0x08048ef3 : jne    8048f01 <main+0x41>
        binary += "\xc7\x04\x24\xc0\x5a\x0c\x08"  # 0x08048ef5 : mov    DWORD PTR [esp],0x80c5ac0
        binary += "\xe8\x4f\x0c\x00\x00"          # 0x08048efc : call   8049b50 <_IO_puts>
        binary += "\xc9"                          # 0x08048f01 : leave
        binary += "\xc3"                          # 0x08048f02 : ret

        self._memory.set_base_address(bin_start_address)
        self._memory.set_content(binary)

        start = 0x08048ec0
        # start = 0x08048ec6
        # end = 0x08048efc
        end = 0x08048f01

        registers = {
            "eax" : GenericRegister("eax", 32, 0xffffd0ec),
            "ecx" : GenericRegister("ecx", 32, 0x00000001),
            "edx" : GenericRegister("edx", 32, 0xffffd0e4),
            "ebx" : GenericRegister("ebx", 32, 0x00000000),
            "esp" : GenericRegister("esp", 32, 0xffffd05c),
            "ebp" : GenericRegister("ebp", 32, 0x08049580),
            "esi" : GenericRegister("esi", 32, 0x00000000),
            "edi" : GenericRegister("edi", 32, 0x08049620),
            "eip" : GenericRegister("eip", 32, 0x08048ec0),
        }

        flags = {
            "af" : GenericFlag("af", 0x0),
            "cf" : GenericFlag("cf", 0x0),
            "of" : GenericFlag("of", 0x0),
            "pf" : GenericFlag("pf", 0x1),
            "sf" : GenericFlag("sf", 0x0),
            "zf" : GenericFlag("zf", 0x1),
        }

        memory = {
        }

        bb_list = self._bb_builder.build(bin_start_address, bin_end_address)

        bb_graph = BasicBlockGraph(bb_list)
        # bb_graph.save("bb_graph.png")
        # bb_graph.save("bb_graph_ir.png", print_ir=True)

        codeAnalyzer = CodeAnalyzer(self._smt_solver, self._smt_translator)

        codeAnalyzer.set_context(GenericContext(registers, flags, memory))

        for bb_path in bb_graph.all_simple_bb_paths(start, end):
            if verbose:
                print "[+] Checking path satisfiability :"
                print "      From : %s" % hex(start)
                print "      To : %s" % hex(end)
                print "      Path : %s" % " -> ".join((map(lambda o : hex(o.address), bb_path)))

            is_sat = codeAnalyzer.check_path_satisfiability(bb_path, start, verbose=False)

            if verbose:
                print "[+] Satisfiability : %s" % str(is_sat)

            self.assertTrue(is_sat)

            if is_sat and verbose:
                print codeAnalyzer.get_context()

            if verbose:
                print ":" * 80
                print ""

def main():
    unittest.main()


if __name__ == '__main__':
    main()