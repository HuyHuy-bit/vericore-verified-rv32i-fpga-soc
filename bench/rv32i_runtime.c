unsigned int __mulsi3(unsigned int left, unsigned int right) {
    unsigned int result = 0;
    while (right != 0) {
        if ((right & 1u) != 0)
            result += left;
        left <<= 1;
        right >>= 1;
    }
    return result;
}

static unsigned int divide_unsigned(
    unsigned int numerator,
    unsigned int denominator,
    unsigned int *remainder
) {
    unsigned int quotient = 0;
    unsigned int value = 0;
    unsigned int index;

    if (denominator == 0) {
        *remainder = numerator;
        return ~0u;
    }
    for (index = 0; index < 32; index++) {
        unsigned int carry = value >> 31;
        value = (value << 1) | (numerator >> 31);
        numerator <<= 1;
        quotient <<= 1;
        if (carry != 0 || value >= denominator) {
            value -= denominator;
            quotient |= 1u;
        }
    }
    *remainder = value;
    return quotient;
}

unsigned int __udivsi3(unsigned int numerator, unsigned int denominator) {
    unsigned int remainder;
    return divide_unsigned(numerator, denominator, &remainder);
}

unsigned int __umodsi3(unsigned int numerator, unsigned int denominator) {
    unsigned int remainder;
    divide_unsigned(numerator, denominator, &remainder);
    return remainder;
}

int __divsi3(int numerator, int denominator) {
    unsigned int left = numerator < 0 ? 0u - (unsigned int)numerator : (unsigned int)numerator;
    unsigned int right = denominator < 0 ? 0u - (unsigned int)denominator : (unsigned int)denominator;
    unsigned int remainder;
    unsigned int quotient = divide_unsigned(left, right, &remainder);
    return (numerator < 0) != (denominator < 0) ? (int)(0u - quotient) : (int)quotient;
}

int __modsi3(int numerator, int denominator) {
    unsigned int left = numerator < 0 ? 0u - (unsigned int)numerator : (unsigned int)numerator;
    unsigned int right = denominator < 0 ? 0u - (unsigned int)denominator : (unsigned int)denominator;
    unsigned int remainder;
    divide_unsigned(left, right, &remainder);
    return numerator < 0 ? (int)(0u - remainder) : (int)remainder;
}
