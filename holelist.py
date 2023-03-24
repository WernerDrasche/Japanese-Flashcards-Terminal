from collections import UserList

class HoleList(UserList):
    def __init__(self, data=[]):
        self.free = []
        super().__init__(data)
    
    def __delitem__(self, i):
        if isinstance(i, slice):
            raise ValueError("slice indexing not supported")
        self.data[i] = None
        if i == len(self.data) - 1:
            for y in range(i, -1, -1):
                if self.data[y]:
                    break
                del self.data[y]
            self.free = [f for f in self.free if f < y]
        else:
            self.free.append(i)

    def __len__(self):
        return len(self.data) - len(self.free)

    def __iter__(self):
        def iterator():
            for element in self.data:
                if element:
                    yield element
        return iterator()

    def add(self, element):
        if self.free:
            i = self.free.pop()
            self.data[i] = element
        else:
            i = len(self.data)
            self.data.append(element)
        return i

if __name__ == "__main__":
    x = HoleList([1,2,3,4,5,6])
    del x[1]
    del x[3]
    del x[4]
    print(x.data, x.free)
    del x[5]
    print(x.data, x.free)
    x.add(2)
    print(x.data, x.free)
    del x[2]
    print(x.data, x.free)
    del x[0]
    print(x.data, x.free)
    del x[1]
    print(x.data, x.free)
    x.add(1)
