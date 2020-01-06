import pdb

def line_passes(line):
	# error messages and class identifiers
	banned = ["die__", "public:", "private:", "protected:"]
	for i in banned:
		if i in line:
			return False
	return True

# in this case we're stripping the enums
def extract_enum(i):
	lines = [i for i in i.split("\n")]
	out_lines = []
	enums = []
	in_enum= -1
	for line in lines:
		if "enum" in line and "{" in line:
			in_enum = 1
			#enums.append(line)
		elif in_enum != -1:
			in_enum += 1
			#enums.append(line)
			if  "}" in line:
				in_enum = -1
		else:
			out_lines.append(line)
	return "\n".join(out_lines) + "\n"+"\n".join(enums)



def strip_struct(output):
	lines = [line for line in output.split("\n")]
	for i in range(len(lines))[1:-1]:
		if len(lines[i].strip()) > 0:
			precomments = lines[i].split("/*")[0]
			objs = precomments.split()
			if "*" in objs:
				objs[0] = "void"
				for j in range(len(objs))[1:]:
					if "*" in objs[j]:
						break
					else:
						objs.pop(j)
			lines[i] = "\t"+" ".join(objs)
	return "\n".join(lines)
				


def get_struct(name, pahole_path, elf_file):
	from subprocess import getoutput
	out =getoutput(pahole_path+" --classes_as_structs --class_name="+name+ " "+elf_file )
	# object refers to a C++ class I didn't want to deal with
	problematic = ["Object"] 

	out = out.replace("class", "struct")
	out = out.replace("TCGLLVMContext", "void")
	out = out.replace("__int128 unsigned", "uint64_t") # cffi doesn't support 128 bit 
	out = "\n".join([i for i in out.split("\n") if line_passes(i)])
	out = extract_enum(out)
	if name in problematic:
		out = strip_struct(out)
	if not out.strip():
		pdb.set_trace()
		print("empty")
	return out

def is_basic_type(a,base):
	return a == "void" or "int" in a or "bool" in a.lower() or a in base

def name_without_ptr(a):
	# specifically we're getting rid of *, but this is a good catch
	from string import ascii_letters, digits
	alphabet = ascii_letters+digits+"_" # alphabet for names
	return "".join([i for i in a if i in alphabet]) 




class Struct(object):
	def __init__(self, name, elf, pahole_path):
		self.name = name
		self.elf = elf
		self.pahole_path = pahole_path
		cont = get_struct(name, pahole_path, elf)
		# get rid of blank lines
		self.content = "\n".join([line for line in cont.split("\n") if line])
		self.circular_depends = []
		self.depends = []

	def add_dependency(self, dependency):
		self.depends.append(dependency)
	
	def add_circular_dependency(self, dependency):
		if dependency in self.depends:
			self.depends.remove(dependency)
		if dependency not in self.circular_depends:
			self.circular_depends.append(dependency)
	
	def __str__(self):
		content = "struct "+self.name+";\ntypedef struct "+self.name +" " + self.name + ";\n"
		for item in self.circular_depends:
			content += "struct "+item.name+";\ntypedef struct "+item.name + " "+item.name +";\n"
		content += self.content + "\n"
		return content
			

class HeaderFile(object):
	def __init__(self, arch, base, pahole_path, elf):
		self.arch = arch
		self.structs = {} # mapping of struct name to struct
		self.lines = {}  # mapping of line # to struct for debugging
		self.base = base
		self.pahole_path = pahole_path
		self.elf = elf

	def add_struct(self, struct_name):
		if struct_name not in self.structs:
			self.structs[struct_name] = Struct(struct_name, self.elf, self.pahole_path)
		else:
			print("Got duplicate")
			pdb.set_trace()


	def render(self):
		self.lines = {}
		struct_ordered_list = []
		self.current_line_num = self.base.count("\n")
		struct_unordered_list = list(self.structs.values())
		struct_unordered_list.sort(key=lambda x: len(x.depends))

		def insert_struct(struct, marked):
			global current_line_num
			m = marked.copy()
			if struct in m:
				print("loop detected:"+" ".join([i.name for i in m]))
				# break loops by finding the first loop node and breaking the dependency to its next item
				print("breaking loop")
				next_item = m[m.index(struct)+1]
				struct.add_circular_dependency(next_item)
			m.append(struct)
			depends = struct.depends
			for sd in depends:
				if sd not in struct_ordered_list:
					insert_struct(sd,m)
			if struct not in struct_ordered_list:
				struct_ordered_list.append(struct)
				lines = str(struct).count("\n")
				for i in range(lines): # gives us a mapping of line num to struct
					self.lines[self.current_line_num+i] = struct
				self.current_line_num += lines
			
		for struct in struct_unordered_list:
			insert_struct(struct, [])

		assert(len(struct_ordered_list) == len(struct_unordered_list))
		return self.base + "".join([str(x) for x in struct_ordered_list])
	

	def get_name(self,lst):
		if "(*" in "".join(lst): # is a function
			# This one is complicated. It could be missing
			# the return type, or any of the arguments.
			# All this to say you may have to implement it.
			# Better than I did anyway.
			a = "".join(lst)
			ret = name_without_ptr(a.split(")(")[0].split("(*")[0])
			args = [name_without_ptr(i) for i in a.split(")(")[1].split(",")]
					
			if not is_basic_type(ret,self.base) and ret not in self.structs:
				return ret
			else:
				for i in range(len(args)):
					if args[i] not in self.structs:
						if not is_basic_type(args[i],self.base):
							return args[i]
		bad = ["const"]
		if lst[0] in bad:
			return lst[1]
		return lst[0]
	
	def parse_error_msg(self, e):
		q = str(e)
		print(q)
		if e.__class__.__name__ == "TypeError":
			split = q.split("'")
			former = split[1].split(".")[0]
			former_obj = self.structs[former]
			former_line = None
			for line in self.lines.keys():
				if self.lines[line] == former_obj:
					former_ret = line
			latter = split[3].split()[1]
			return latter, former_ret
		elif e.__class__.__name__ == "ValueError":
			split = q.split("'")
			struct = split[1].split()[1]
			# It has to be before CPUState
			former = self.structs["CPUState"]
			fline = 0
			for line in self.lines.keys():
				if self.lines[line] == former:
					fline = line
			return struct, fline
		else:
			try:
				missing = q.split('"')[1]
			except:
				pdb.set_trace()
			print(missing)
			missing_type = self.get_name(missing.split())
			if missing_type == "void":
				pdb.set_trace()
			line = q.split('<cdef source string>:')[1].split(':')[0]
		return missing_type, int(line)

	def validate(self):
		from cffi import FFI
		global comptries
		comptries += 1
		try:
			self.ffi = FFI()
			self.ffi.cdef(self.render())		
			cpustate = self.ffi.new("CPUState*")
			self.ffi.new("CPU"+self.arch+"State*")
			self.ffi.new("TranslationBlock*")
			self.ffi.new("MachineState*")
			self.ffi.new("Monitor*")
			return False
		except Exception as e:
			return self.parse_error_msg(e)
	


def generate_config(arch, bits, pahole_path, elf_file):
	# a bunch of host assumptions. Including a blatantly wrong one. Though I can't seem to fix it.
	assumptions = open("./assumptions.h","r").read()
	base = "typedef uint"+str(bits)+"_t target_ulong;\n"+assumptions
	global header
	header = HeaderFile(arch, base, pahole_path, elf_file)
	# the truth of the matter is we don't need 1000s of QEMU structs. We need 3.
	# We also need the tree created by references to those.
	struct_list = ["QemuThread", "QemuCond", "qemu_work_item","CPUAddressSpace",
	"GDBRegisterState", "CPUState", "TranslationBlock", "MachineState", "Monitor"]

	for struct in struct_list:
		header.add_struct(struct)

	# correction to make this not architecture neutral
	CPUState = header.structs["CPUState"]
	CPUState.content = CPUState.content.replace("void *                     env_ptr;", "CPU"+arch+"State *                     env_ptr;")
	previous = "CPUState"
	loopcounter = 0
	while True:
		valid = header.validate()		
		if valid:
			missing, line = valid
			if missing == previous:
				loopcounter += 1
				print("Looks like you're in a loop!")
				if loopcounter >= 10:
					pdb.set_trace()
			else:
				loopcounter = 0
			previous = missing
			print("It seems to have a dependency from "+header.lines[line].name +" on " + missing)
			if missing not in header.structs: # truly missing
				print("adding "+missing)
				header.add_struct(missing)
			print("adding dependency")
			header.lines[line].add_dependency(header.structs[missing])
		else:
			break
	
	OUT_FILE_NAME = "./output/panda_datatypes_"+arch+"_"+str(bits)+".h"
	with open(OUT_FILE_NAME,"w") as f:
		f.write(header.render())
	print("Finished. Content written to "+OUT_FILE_NAME)

comptries = 0
panda_base = "~/workspace/panda/build/"
pahole_path = "~/workspace/pahole/build/pahole" # do not use the ubuntu version. build it from github

archs = [("X86", 32,"/i386-softmmu/libpanda-i386.so"),
		("X86", 64, "/x86_64-softmmu/libpanda-x86_64.so"),
		("ARM", 32, "/arm-softmmu/libpanda-arm.so"),
		("PPC", 32, "/ppc-softmmu/libpanda-ppc.so"),
		("PPC", 64, "/ppc64-softmmu/libpanda-ppc64.so")
		]

for arch in archs:
	generate_config(arch=arch[0], bits=arch[1], pahole_path=pahole_path, elf_file=panda_base+arch[2])

print("Number of compilation tries: " + str(comptries))
