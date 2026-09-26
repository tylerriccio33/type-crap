"""RD007-RD011: class shapes carried over from other languages."""

import pytest


def test_rd007_getter_setter(check):
    out = check(
        """
        class P:
            def __init__(self, n):
                self._name = n
                self.extra = 1

            def get_name(self):
                return self._name

            def set_name(self, v):
                self._name = v
        """
    )
    assert out == [
        "RD007 `P.get_name` just returns `self._name`; make `name` a plain attribute",
        "RD007 `P.set_name` just assigns `self._name`; make `name` a plain attribute",
    ]


def test_rd007_getter_that_computes_is_fine(codes):
    assert not codes(
        """
        class P:
            def get_name(self):
                return self._name.title()

            def set_name(self, v):
                self._name = v.strip()

            def other(self):
                pass
        """
    )


def test_rd008_proxy_property(check):
    out = check(
        """
        class P:
            @property
            def name(self):
                return self._name

            @name.setter
            def name(self, v):
                self._name = v

            def other(self):
                pass
        """
    )
    assert out == [
        "RD008 `P.name` property and setter only proxy `self._name`; make `name` a plain attribute"
    ]


def test_rd008_read_only_property_is_fine(codes):
    assert not codes(
        """
        class P:
            @property
            def name(self):
                return self._name

            def other(self):
                pass
        """
    )


def test_rd008_validating_setter_is_fine(codes):
    assert not codes(
        """
        class P:
            @property
            def name(self):
                return self._name

            @name.setter
            def name(self, v):
                if not v:
                    raise ValueError
                self._name = v

            def other(self):
                pass
        """
    )


def test_rd009_staticmethod_namespace(check):
    out = check(
        """
        class Utils:
            \"\"\"helpers\"\"\"

            @staticmethod
            def a():
                return 1

            @staticmethod
            def b():
                return 2
        """
    )
    assert out == ["RD009 `Utils` only holds staticmethods; use module-level functions"]


@pytest.mark.parametrize(
    "src",
    [
        # has state
        "class U:\n    X = 1\n    @staticmethod\n    def a():\n        pass\n",
        # subclass / protocol implementation
        "class U(Base):\n    @staticmethod\n    def a():\n        pass\n",
        # mixed
        "class U:\n    @staticmethod\n    def a():\n        pass\n    @classmethod\n"
        "    def b(cls):\n        pass\n",
    ],
)
def test_rd009_fine(codes, src):
    assert codes(src) == []


def test_rd010_one_method_class(check):
    out = check(
        """
        class Greeter:
            def __init__(self, name):
                self.name = name

            def greet(self):
                return f"hi {self.name}"
        """
    )
    assert out == [
        "RD010 `Greeter` is `__init__` plus `greet`; make `greet` a function that takes the"
        " constructor args"
    ]


@pytest.mark.parametrize(
    "src",
    [
        # init does work
        "class G:\n    def __init__(self, n):\n        self.n = n\n        register(self)\n"
        "    def greet(self):\n        pass\n",
        # dunder protocol
        "class G:\n    def __init__(self, n):\n        self.n = n\n"
        "    def __call__(self):\n        pass\n",
        # decorated class
        "@dataclass\nclass G:\n    def __init__(self, n):\n        self.n = n\n"
        "    def greet(self):\n        pass\n",
        # two methods
        "class G:\n    def __init__(self, n):\n        self.n = n\n"
        "    def a(self):\n        pass\n    def b(self):\n        pass\n",
    ],
)
def test_rd010_fine(codes, src):
    assert "RD010" not in codes(src)


@pytest.mark.parametrize(
    "sig, call",
    [
        ("self, a, b", "a, b"),
        ("self, *args, **kwargs", "*args, **kwargs"),
        ("self, a, *, k", "a, k=k"),
    ],
)
def test_rd011_useless_super(codes, sig, call):
    assert codes(
        f"""
        class C(Base):
            def __init__({sig}):
                super().__init__({call})
        """
    ) == ["RD011"]


def test_rd011_return_form_and_message(check):
    out = check(
        """
        class C(Base):
            def run(self, x):
                return super().run(x)
        """
    )
    assert out == ["RD011 `C.run` only calls `super().run` with the same args; delete it"]


@pytest.mark.parametrize(
    "src",
    [
        # changes an argument
        "class C(B):\n    def __init__(self, a):\n        super().__init__(a, 1)\n",
        # changes a default
        "class C(B):\n    def __init__(self, a=2):\n        super().__init__(a)\n",
        # reorders
        "class C(B):\n    def f(self, a, b):\n        return super().f(b, a)\n",
        # calls a different method
        "class C(B):\n    def f(self, a):\n        return super().g(a)\n",
        # decorated (e.g. @override, @abstractmethod-adjacent)
        "class C(B):\n    @cache\n    def f(self, a):\n        return super().f(a)\n",
    ],
)
def test_rd011_fine(codes, src):
    assert codes(src) == []
