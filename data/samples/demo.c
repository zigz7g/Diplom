#include <stdio.h>
#include <stdlib.h>

int main() {
    int x;
    int *p = NULL;
    if (rand() % 2) {
        p = (int*)malloc(sizeof(int));
    }
    printf("%d\n", x); // uninitialized use
    *p = 42; // possible null deref
    if (p) free(p);
    return 0;
}
