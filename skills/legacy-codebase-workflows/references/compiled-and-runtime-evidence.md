# Compiled and runtime evidence

Read this when the source cannot settle a question: the project no longer imports into an IDE, a library ships without source, the deployed archive may differ from the checkout, or a claim about the code ("this method is static", "nothing calls this") needs proof instead of a model's recollection.

Work from the cheapest evidence upward: source first, then the compiled classes, then a running program. Static evidence never shows that code executed. Record which kind each conclusion rests on.

## Compiled classes answer exact questions

The JDK ships tools that read class files and JARs directly. They need a JDK on the machine and the compiled output, which exists wherever the application is built or deployed. They do not need the project to open in an IDE or a working build of the whole repository.

**Members, modifiers and call sites: `javap`.** Name a class by its fully qualified name with `-cp`, by the path of its `.class` file, or by a `jar:file:` URL.

```bash
javap -p -cp build/classes com.example.billing.Orders
```

`-p` shows all classes and members, including private ones. This answers visibility, `static`, `final` and exact signature questions. `-c` prints the bytecode of every method. Each call appears as an invoke instruction naming the owner class and the full descriptor of the target, so it shows which overload the compiler actually bound. `-constants` shows the values of `static final` constants, `-s` prints internal type signatures, `-l` prints line and local variable tables, and `-v` prints everything including the class file version.

**Who depends on what: `jdeps`.** It accepts class files, directories and JARs. Give the dependency JARs with `-cp`, separated by the platform's path separator.

```bash
jdeps -verbose:class -cp lib/reports.jar build/app.jar
```

`-s` prints a summary per archive. `-verbose:class` prints class-level dependencies. `-p <package>` and `-e <regex>` find the classes that depend on one package, which is the fast way to measure how much code touches an old library before replacing it. `--jdk-internals` finds dependencies on JDK internal APIs, the usual first obstacle when moving an old application to a current Java release. `-R` follows run-time dependencies recursively and `--ignore-missing-deps` continues when a dependency is absent.

**Deprecated Java SE API use: `jdeprscan`.** It scans a directory, JAR or class and needs the dependent classes on `--class-path`.

```bash
jdeprscan --class-path lib/reports.jar build/app.jar
```

`--for-removal` limits the report to APIs deprecated for removal. It reports deprecations defined by Java SE only, not those of third-party libraries.

**Two versions of a library.** Before a migration between distant versions, print the API of the classes your code calls from both JARs with `javap` and compare the outputs. The differences are the migration work list, taken from the artifacts and not from documentation that may describe another version.

**Checkout against deployment.** When there is doubt that the repository matches what runs, list the classes in the deployed archive and compare them with the build output. Classes present only in the archive, or only in the source, are findings to resolve before trusting either.

**Libraries without source.** A decompiler such as CFR, Vineflower or JADX turns a JAR into readable Java. Treat the result as a reading aid and an inference: decompiled code can differ from the original, so confirm each fact that matters with `javap`. Check the library's license before decompiling it, and keep decompiled code out of the repository.

Record this evidence like a source citation: the artifact path, its SHA-256, the tool and JDK version, and the exact command. A class file is the output of one build, so name the build or archive it came from.

## Runtime observation with `jdb`

Use a debugger when static evidence cannot answer: which branch runs for a given input, what a value is at a certain line, where an exception is first thrown. `jdb` is the JDK's command-line debugger, so an agent can set breakpoints and read state without anyone clicking in an IDE.

Only do this in a test environment you are authorized to run, with data that may be shown to the model provider. Values read at a breakpoint become part of the conversation.

Start the target JVM with the debug agent, listening on the loopback address:

```bash
java -agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=8000 -cp build/classes com.example.Main
```

`suspend=n` lets the program start normally; the default `suspend=y` waits for the debugger before the main class loads. An address without a host listens on loopback only. `address=*:8000` listens on every network interface and lets anyone who can reach the port control the JVM, so do not use it on a shared network. Add the same option to an application server's JVM arguments to debug a deployed web application in a test instance.

Attach from a second terminal, pointing at the source so that listings work:

```bash
jdb -attach 8000 -sourcepath src/main/java
```

| Command | Effect |
| --- | --- |
| `stop at com.example.Orders:120` | Breakpoint at a source line |
| `stop in com.example.Orders.total` | Breakpoint at the start of a method; add the parameter types to select an overload |
| `catch java.lang.IllegalStateException` | Stop where that exception, or a subclass, is thrown |
| `cont`, `step`, `next` | Continue, step into, step over |
| `clear com.example.Orders:120` | Remove a breakpoint; `clear` alone lists them |
| `help` | The full command list, including stack and variable inspection |

Local variable names are available only when the classes were compiled with debug information. Drive `jdb` from a persistent terminal session or pane, not from a one-shot pipe: a breakpoint is reported when the program reaches it, and the next command has to wait for that.

Record a runtime finding as observed, with the scenario, the input, the revision and the commands used. One observed run shows what happened for that input, not what happens for all inputs.

## Where REA fits

[REA](https://github.com/morluto/rea) is an MCP server and CLI for reverse engineering shipped artifacts. Its own instructions say to use normal repository tools for analysis of a source repository, and at version 6.4.0 it has no route for JVM class files or JARs. For a legacy codebase it is worth setting up only for these cases:

- **Native libraries without source**, such as JNI libraries an old application loads. REA drives Ghidra, Hopper or IDA to return pseudocode, strings, symbols and references. Hopper and IDA are commercial products under their own licenses.
- **Recorded traffic of an old web application.** REA reads a HAR file offline and groups the observed requests by method, origin and path template. That is an inventory of the endpoints actually used, to characterize before a rewrite. A HAR file can contain credentials and personal data; record it in a test environment and treat it as sensitive.
- **Two runs of a command-line program.** Its process capture records terminal output, exit status and selected filesystem state for comparison, on Linux and macOS.

REA's documentation installs with `npx -y rea-agents@latest`. Pin a reviewed version instead, and run its setup with `--dry-run` first, because setup changes agent configuration. Analyze only software you own or are authorized to examine.
